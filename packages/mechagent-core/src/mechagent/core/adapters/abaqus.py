"""Abaqus/Standard 求解器适配器。

适配器使用与 CalculiX 相同的显式结构输入模型，调用本机 Abaqus launcher，
并通过 Abaqus Python 解释器读取 ODB 的节点结果场。Abaqus 不可用、许可证
不可用、ODB 缺失或场量提取失败都会返回失败结果，不降级为 CalculiX。
"""

from __future__ import annotations

import json
import math
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from mechagent.core.cad import is_multi_solid_cad_metadata
from mechagent.core.exceptions import SolverError
from mechagent.core.executor import (
    AbstractJobExecutor,
    ExecutorConfig,
    JobSpec,
    JobStatus,
    LocalCommandExecutor,
)
from mechagent.core.license_queue import FileLicenseQueue, LicenseQueueError
from mechagent.core.models import AnalysisType, GeometryType, ModelParams, SimulationCase
from mechagent.core.paths import safe_file_stem
from mechagent.core.results import attach_case_result_fields, attach_mapped_result_fields
from mechagent.core.solver import (
    AbstractSolver,
    SolverConfig,
    SolverResult,
    enrich_solver_result,
    solver_result_provenance,
)

from .calculix import _beam_static_inp, _plate_static_inp, _solid_static_inp


@dataclass(frozen=True)
class AbaqusExecutionPolicy:
    """Abaqus 许可证探针、本地并发配额和可选跨进程租约队列。

    ``license_probe`` 是可选的只读命令模板，例如
    ``("abaqus", "licensing", "ru")``。命令返回非零状态时作业拒绝提交。
    ``queue_path`` 指向共享 SQLite 数据库时，多个 Python 进程会共同遵守
    ``max_concurrent``；未配置时只约束当前进程。集群许可证服务单独管理容量和可用性。
    """

    max_concurrent: int = 1
    license_probe: tuple[str, ...] | None = None
    queue_path: Path | None = None
    lease_seconds: float = 900.0
    poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("Abaqus max_concurrent 必须为正数。")
        if self.license_probe is not None and any(not item.strip() for item in self.license_probe):
            raise ValueError("Abaqus license_probe 不能包含空命令片段。")
        if self.lease_seconds <= 0 or not math.isfinite(self.lease_seconds):
            raise ValueError("Abaqus license lease_seconds 必须为正的有限数值。")
        if self.poll_interval_seconds <= 0 or not math.isfinite(self.poll_interval_seconds):
            raise ValueError("Abaqus license poll_interval_seconds 必须为正的有限数值。")


_POLICY_LOCK = threading.Lock()
_POLICY_SEMAPHORES: dict[tuple[str, int], threading.BoundedSemaphore] = {}


def _policy_semaphore(launcher: str, policy: AbaqusExecutionPolicy) -> threading.BoundedSemaphore:
    key = (launcher, policy.max_concurrent)
    with _POLICY_LOCK:
        return _POLICY_SEMAPHORES.setdefault(key, threading.BoundedSemaphore(policy.max_concurrent))


def _canonicalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "U": "displacement",
        "S": "stress",
        "E": "strain",
        "EVOL": "volume",
        "SENER": "strain_energy_density",
        "RF": "reaction_force",
        "ENER": "energy",
        "ELSE": "energy",
    }
    return {aliases.get(str(key).upper(), str(key).lower()): value for key, value in fields.items()}


class AbaqusAdapter(AbstractSolver):
    """Abaqus/Standard 线性静力适配器。

    输入模板覆盖当前结构静力几何族；求解完成必须生成 ODB，结果提取使用
    `abaqus python` 调用 ODB API，不依赖宿主 Python 的 `odbAccess` 模块。
    """

    def __init__(
        self,
        config: SolverConfig,
        executor: Optional[AbstractJobExecutor] = None,
        *,
        policy: AbaqusExecutionPolicy | None = None,
    ) -> None:
        super().__init__(config)
        self.executor = executor or LocalCommandExecutor(
            ExecutorConfig(work_dir=config.work_dir, default_timeout=config.timeout)
        )
        self.policy = policy or AbaqusExecutionPolicy(
            max_concurrent=config.max_concurrent,
            license_probe=config.license_probe,
            queue_path=config.license_queue_path,
            lease_seconds=config.license_lease_seconds,
        )

    def generate_input(self, model_params: ModelParams) -> Path:
        if model_params.analysis.type is not AnalysisType.STATIC:
            raise SolverError("AbaqusAdapter 当前只支持线性静力分析。")
        if model_params.analysis.nlgeom:
            raise SolverError("AbaqusAdapter 当前只支持 nlgeom=False。")
        if model_params.geometry.type is GeometryType.BEAM:
            content = _beam_static_inp(model_params, model_params.mesh_file)
        elif model_params.geometry.type is GeometryType.PLATE:
            content = _plate_static_inp(model_params, model_params.mesh_file)
        elif model_params.geometry.type is GeometryType.SOLID:
            if is_multi_solid_cad_metadata(model_params.metadata):
                raise SolverError(
                    "CAD 多实体模型缺少连接或接触契约，当前求解器只接受单实体 CAD 求解。"
                )
            content = _solid_static_inp(model_params, model_params.mesh_file)
        else:
            raise SolverError(
                f"AbaqusAdapter 不支持 {model_params.geometry.type.value} 几何输入生成。"
            )
        content = _configure_abaqus_step(content, "step-1", increments=1)
        case_id = safe_file_stem(model_params.case_id, "RUN_abaqus")
        path = self.config.work_dir / f"{case_id}.inp"
        path.write_text(content, encoding="utf-8")
        return path

    def solve(self, input_file: Path) -> SolverResult:
        if not input_file.is_file():
            raise SolverError(f"Abaqus 输入文件不存在: {input_file}")
        launcher = _resolve_launcher(str(self.config.solver_path))
        if launcher is None:
            return SolverResult(
                success=False,
                wall_time=0.0,
                error_message=f"未找到 Abaqus launcher: {self.config.solver_path}",
            )
        job_name = input_file.stem
        spec = JobSpec(
            command=[launcher, f"job={job_name}", f"input={input_file.name}", "interactive"],
            work_dir=input_file.parent,
            timeout=self.config.timeout,
            labels={"solver": "abaqus", "analysis": "static"},
        )
        try:
            with self._execution_slot(launcher):
                job_result = self.executor.run(spec)
        except SolverError as exc:
            return SolverResult(success=False, wall_time=0.0, error_message=str(exc))
        output_files = sorted(input_file.parent.glob(f"{job_name}.*"))
        odb = input_file.parent / f"{job_name}.odb"
        lock = input_file.parent / f"{job_name}.lck"
        if job_result.status is not JobStatus.SUCCEEDED:
            return SolverResult(
                success=False,
                wall_time=job_result.wall_time,
                output_files=output_files,
                error_message=job_result.stderr.strip()
                or job_result.stdout.strip()
                or job_result.error_message
                or "Abaqus 求解失败。",
            )
        if lock.exists():
            return SolverResult(
                success=False,
                wall_time=job_result.wall_time,
                output_files=output_files,
                error_message="Abaqus 求解结束但 ODB 仍被锁定。",
            )
        if not odb.is_file():
            return SolverResult(
                success=False,
                wall_time=job_result.wall_time,
                output_files=output_files,
                error_message="Abaqus 未生成 ODB 结果文件。",
            )
        extraction = self._extract_odb(launcher, odb, input_file.parent)
        if extraction is None:
            return SolverResult(
                success=False,
                wall_time=job_result.wall_time,
                output_files=output_files,
                error_message="Abaqus ODB 结果场提取失败。",
            )
        output_files = sorted({*output_files, extraction})
        return SolverResult(
            success=True,
            wall_time=job_result.wall_time,
            output_files=output_files,
            summary={
                "job_name": job_name,
                "backend": "abaqus-standard",
                "odb": str(odb),
                "field_json": str(extraction),
                "returncode": job_result.return_code,
            },
        )

    def extract_results(self, result: SolverResult) -> dict[str, Any]:
        if not result.success:
            raise SolverError(result.error_message or "Abaqus 求解失败。")
        field_path = Path(str(result.summary.get("field_json", "")))
        if not field_path.is_file():
            raise SolverError("Abaqus 结果场 JSON 不存在。")
        try:
            fields = json.loads(field_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SolverError("Abaqus 结果场 JSON 无法读取。") from exc
        if not isinstance(fields, dict) or not fields.get("steps"):
            raise SolverError("Abaqus ODB 未提供有效分析步结果场。")
        steps = fields["steps"]
        if not isinstance(steps, list):
            raise SolverError("Abaqus ODB 分析步结果格式无效。")
        final_fields: dict[str, Any] = {}
        history: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("fields"), dict):
                continue
            final_fields = _canonicalize_fields(step["fields"])
            for frame in step.get("frames", []):
                if isinstance(frame, dict) and isinstance(frame.get("fields"), dict):
                    history.append(
                        {
                            "step_name": step.get("name"),
                            "frame_index": frame.get("frame_index"),
                            **_canonicalize_fields(frame["fields"]),
                        }
                    )
        if not final_fields:
            raise SolverError("Abaqus ODB 未提供可用的最终结果场。")
        extracted: dict[str, Any] = {
            "success": True,
            "output_files": [str(path) for path in result.output_files],
            **solver_result_provenance(result),
            "fields": final_fields,
            "field_history": history,
            "steps": steps,
            **result.summary,
        }
        if isinstance(fields.get("nodes"), dict):
            extracted["nodes"] = fields["nodes"]
        if isinstance(fields.get("elements"), dict):
            extracted["elements"] = fields["elements"]
        if isinstance(fields.get("element_centroids"), dict):
            extracted["element_centroids"] = fields["element_centroids"]
        return extracted

    def run_case(self, case: SimulationCase) -> dict[str, Any]:
        case.ensure_execution_ready()
        if any(step.analysis is not AnalysisType.STATIC or step.nlgeom for step in case.load_steps):
            raise SolverError("Abaqus 多步执行当前只支持线性静力分析。")
        if not case.load_steps:
            raise SolverError("案例至少需要一个分析步。")
        contents = [
            self._input_content(case.to_step_model_params(step.step_id)) for step in case.load_steps
        ]
        prefix = contents[0].split("*STEP", 1)[0]
        sections = ["*STEP" + content.split("*STEP", 1)[1] for content in contents]
        sections = [
            _configure_abaqus_step(section, step.step_id, step.increments)
            for section, step in zip(sections, case.load_steps, strict=True)
        ]
        case_id = safe_file_stem(case.case_id or case.model.case_id, "RUN_abaqus")
        input_file = self.config.work_dir / f"{case_id}.inp"
        input_file.write_text(prefix + "".join(sections), encoding="utf-8")
        result = self.solve(input_file)
        result = enrich_solver_result(result, input_file)
        extracted = self.extract_results(result)
        extracted = attach_case_result_fields(extracted, case)
        extracted = attach_mapped_result_fields(extracted, case)
        extracted["load_steps"] = [step.model_dump(mode="json") for step in case.load_steps]
        extracted["result_fields"] = [field.model_dump(mode="json") for field in case.result_fields]
        extracted["step_count"] = len(case.load_steps)
        return extracted

    def _input_content(self, model_params: ModelParams) -> str:
        if model_params.geometry.type is GeometryType.BEAM:
            return _beam_static_inp(model_params, model_params.mesh_file)
        if model_params.geometry.type is GeometryType.PLATE:
            return _plate_static_inp(model_params, model_params.mesh_file)
        if model_params.geometry.type is GeometryType.SOLID:
            if is_multi_solid_cad_metadata(model_params.metadata):
                raise SolverError(
                    "CAD 多实体模型缺少连接或接触契约，当前求解器只接受单实体 CAD 求解。"
                )
            return _solid_static_inp(model_params, model_params.mesh_file)
        raise SolverError(f"AbaqusAdapter 不支持 {model_params.geometry.type.value} 几何输入生成。")

    def _extract_odb(self, launcher: str, odb: Path, work_dir: Path) -> Path | None:
        script = work_dir / f"{odb.stem}_extract.py"
        output = work_dir / f"{odb.stem}.fields.json"
        script.write_text(_odb_script(odb, output), encoding="utf-8")
        result = self.executor.run(
            JobSpec(
                command=[launcher, "python", script.name],
                work_dir=work_dir,
                timeout=self.config.timeout,
                labels={"solver": "abaqus", "operation": "odb_extract"},
            )
        )
        return output if result.status is JobStatus.SUCCEEDED and output.is_file() else None

    @contextmanager
    def _execution_slot(self, launcher: str) -> Iterator[None]:
        semaphore = _policy_semaphore(launcher, self.policy)
        if not semaphore.acquire(timeout=self.config.timeout):
            raise SolverError("Abaqus 本地执行队列已满，等待许可证槽位超时。")
        lease: Any = None
        lease_context: Any = None
        try:
            if self.policy.queue_path is not None:
                try:
                    queue = FileLicenseQueue(
                        self.policy.queue_path,
                        launcher,
                        self.policy.max_concurrent,
                        lease_seconds=self.policy.lease_seconds,
                        poll_interval_seconds=self.policy.poll_interval_seconds,
                    )
                    lease_context = queue.acquire(self.config.timeout)
                    lease = lease_context.__enter__()
                except LicenseQueueError as exc:
                    raise SolverError(str(exc)) from exc
            if self.policy.license_probe is not None:
                probe_command = [
                    launcher if item == "{launcher}" else item for item in self.policy.license_probe
                ]
                if "{launcher}" not in self.policy.license_probe:
                    probe_command.insert(0, launcher)
                probe = self.executor.run(
                    JobSpec(
                        command=probe_command,
                        work_dir=self.config.work_dir,
                        timeout=min(self.config.timeout, 60),
                        labels={"solver": "abaqus", "operation": "license_probe"},
                    )
                )
                if probe.status is not JobStatus.SUCCEEDED:
                    detail = probe.stderr.strip() or probe.stdout.strip() or probe.error_message
                    raise SolverError(f"Abaqus 许可证探针失败: {detail or '未知错误'}")
            yield
        finally:
            if lease is not None:
                lease_context.__exit__(None, None, None)
            semaphore.release()


def _resolve_launcher(value: str) -> str | None:
    path = Path(value)
    if path.is_file():
        return str(path)
    return shutil.which(value)


def _configure_abaqus_step(section: str, step_id: str, increments: int) -> str:
    """为多步输入设置稳定的步骤名和最大增量数。"""

    lines = section.splitlines()
    cleaned: list[str] = []
    legacy_output_marker = False
    for line in lines:
        stripped = line.strip().upper()
        if stripped in {"*NODE FILE", "*EL FILE", "*ELEMENT FILE"}:
            legacy_output_marker = True
            continue
        if legacy_output_marker and not stripped.startswith("*"):
            legacy_output_marker = False
            continue
        legacy_output_marker = False
        cleaned.append(line)
    lines = cleaned
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().upper().startswith("*STEP"):
            lines[index] = f"*STEP, NAME={step_id}, INC={increments}"
        elif line.strip().upper().startswith("*STATIC"):
            lines[index] = "*STATIC"
            if index + 1 >= len(lines) or lines[index + 1].lstrip().startswith("*"):
                lines.insert(index + 1, "1., 1., 1e-5, 1.")
                index += 1
        elif line.strip().upper().startswith("*END STEP"):
            lines[index:index] = [
                "*OUTPUT, FIELD, NUMBER INTERVAL=1",
                "*NODE OUTPUT",
                "U, RF",
                "*ELEMENT OUTPUT, POSITION=INTEGRATION POINTS",
                "S, E, EVOL, SENER",
                "*OUTPUT, HISTORY, FREQUENCY=1",
                "*ENERGY OUTPUT",
                "ALLIE, ALLSE, ALLWK, ALLPD",
            ]
            index += 8
        index += 1
    return "\n".join(lines) + "\n"


def _odb_script(odb: Path, output: Path) -> str:
    odb_literal = repr(str(odb.resolve()))
    output_literal = repr(str(output.resolve()))
    return f"""# -*- coding: utf-8 -*-
import json
from odbAccess import openOdb

def _flatten(data):
    try:
        data = data.tolist()
    except AttributeError:
        pass
    if isinstance(data, (tuple, list)):
        values = []
        for item in data:
            values.extend(_flatten(item))
        return values
    return [float(data)]

def _field_location(key):
    if key in ("U", "RF"):
        return "node"
    if key in ("S", "E", "SENER", "ENER"):
        return "integration_point"
    return "element"

def _value_key(value, index):
    node_label = getattr(value, "nodeLabel", None)
    if node_label is not None:
        return str(int(node_label))
    element_label = getattr(value, "elementLabel", None)
    if element_label is None:
        return "index:" + str(index)
    key = str(int(element_label))
    integration_point = getattr(value, "integrationPoint", None)
    if integration_point is not None:
        key += "@ip" + str(int(integration_point))
    section_point = getattr(value, "sectionPoint", None)
    section_number = getattr(section_point, "number", None)
    if section_number is not None:
        key += "@section" + str(int(section_number))
    return key

def _field_units(key):
    return {{
        "U": "mm",
        "RF": "N",
        "S": "MPa",
        "E": "",
        "EVOL": "mm^3",
        "SENER": "N/mm^2",
        "ENER": "N*mm",
    }}.get(key, "")

def _field_payload(key, field_output):
    values = {{}}
    for index, value in enumerate(field_output.values):
        data = _flatten(value.data)
        payload = data[0] if len(data) == 1 else data
        values[_value_key(value, index)] = payload
    return {{"location": _field_location(key), "unit": _field_units(key), "values": values}}

def _history_payload(step):
    history = {{}}
    for region in step.historyRegions.values():
        for key in ("ALLIE", "ALLSE", "ALLWK", "ALLPD"):
            if key in region.historyOutputs and key not in history:
                history[key] = [
                    [float(time), float(value)]
                    for time, value in region.historyOutputs[key].data
                ]
    return history

odb = openOdb(path={odb_literal}, readOnly=True)
try:
    steps = []
    for name, step in odb.steps.items():
        frames = []
        for frame_index, frame in enumerate(step.frames):
            fields = {{}}
            for key in ("U", "S", "E", "EVOL", "SENER", "ENER", "RF"):
                if key not in frame.fieldOutputs:
                    continue
                fields[key] = _field_payload(key, frame.fieldOutputs[key])
            frames.append({{"frame_index": frame_index, "fields": fields}})
        history = _history_payload(step)
        energy_history = history.get("ALLIE", [])
        for frame_index, frame in enumerate(frames):
            if frame_index < len(energy_history):
                frame["fields"]["ENER"] = {{
                    "location": "global",
                    "unit": "N*mm",
                    "values": {{"ALLIE": energy_history[frame_index][1]}},
                }}
        final_fields = frames[-1]["fields"] if frames else {{}}
        steps.append({{"name": name, "frame": len(step.frames) - 1,
                      "fields": final_fields, "frames": frames, "history": history}})
    nodes = {{}}
    elements = {{}}
    element_centroids = {{}}
    for instance_name, instance in odb.rootAssembly.instances.items():
        for node in instance.nodes:
            label = str(int(node.label))
            if label in nodes:
                raise RuntimeError("多个实例存在重复节点标签，无法生成无歧义的节点场。")
            nodes[label] = [float(value) for value in node.coordinates]
        for element in instance.elements:
            label = str(int(element.label))
            if label in elements:
                raise RuntimeError("多个实例存在重复单元标签，无法生成无歧义的单元场。")
            connectivity = [str(int(value)) for value in element.connectivity]
            elements[label] = connectivity
            points = [nodes[node] for node in connectivity]
            element_centroids[label] = [
                sum(point[index] for point in points) / len(points)
                for index in range(3)
            ]
    with open({output_literal}, "w") as stream:
        json.dump(
            {{"solver": "Abaqus/Standard", "steps": steps, "nodes": nodes,
              "elements": elements, "element_centroids": element_centroids}},
            stream,
            sort_keys=True,
        )
finally:
    odb.close()
"""
