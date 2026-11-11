"""在独立目录验证本机 Abaqus 几何、网格和线弹性静力求解。"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Any


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    """按位移、应力和几何参考值判定独立工具检查。"""
    errors: dict[str, float] = {}
    for quantity, reference, target in (
        ("end_ux_mm", "reference_ux_mm", 100.0 / 210000.0),
        ("mean_s11_mpa", "reference_s11_mpa", 1.0),
    ):
        value, reported_target = float(result[quantity]), float(result[reference])
        if not math.isfinite(value) or not math.isfinite(reported_target):
            raise ValueError(f"非有限结果或无效参考值: {quantity}")
        if not math.isclose(reported_target, target, rel_tol=1e-12):
            raise ValueError(f"参考值与固定模型不符: {reference}")
        errors[quantity] = abs(value - target) / abs(target)
    volume = float(result["volume_mm3"])
    if not math.isfinite(volume):
        raise ValueError("非有限几何体积")
    passed = (
        result["job_status"] == "COMPLETED"
        and int(result["node_count"]) > 0
        and int(result["element_count"]) > 0
        and abs(volume - 10000.0) < 0.01
        and all(error <= 0.01 for error in errors.values())
    )
    return {**result, "relative_errors": errors, "tolerance": 0.01, "passed": passed}


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--abaqus", default="abaqus", help="Abaqus 启动器路径或命令名")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, default=Path("mechagent_output/abaqus_smoke"))
    args = parser.parse_args(argv)
    launcher = shutil.which(args.abaqus)
    if launcher is None:
        parser.error("Abaqus 启动器不可用。请使用 --abaqus 指定完整路径。")
    if args.timeout <= 0:
        parser.error("--timeout 必须为正整数")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="RUN_", dir=args.output_dir.resolve()))
    template = Path(__file__).parent / "abaqus" / "linear_static_smoke.py.tmpl"
    script = run_dir / "smoke.py"
    shutil.copyfile(template, script)
    log_path = run_dir / "abaqus.log"
    with log_path.open("w", encoding="utf-8") as log:
        try:
            process = subprocess.run(
                [launcher, "cae", f"noGUI={script}"],
                cwd=run_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(json.dumps({"passed": False, "error": "Abaqus 超时", "log": str(log_path)}))
            return 1
    result_path = run_dir / "result.json"
    if process.returncode != 0 or not result_path.is_file():
        print(
            json.dumps(
                {
                    "passed": False,
                    "return_code": process.returncode,
                    "error": "Abaqus 未生成有效结果",
                    "log": str(log_path),
                }
            )
        )
        return 1
    result = validate_result(json.loads(result_path.read_text(encoding="utf-8")))
    result["work_dir"] = str(run_dir)
    result["scope"] = "standalone_tool_check"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
