from __future__ import annotations

import pytest

from mechagent.core import (
    attach_case_result_fields,
    attach_mapped_result_fields,
    compute_case_digest,
    compute_physical_case_digest,
)
from mechagent.core.exceptions import SolverError
from mechagent.core.models import LoadStepSpec, ResultFieldSpec, SimulationCase
from mechagent.core.validation import tc01_model_params, tc03_model_params


def _case() -> SimulationCase:
    case = SimulationCase.from_model_params(tc01_model_params(), provenance_confidence=1.0)
    return case.model_copy(
        update={
            "result_fields": [
                ResultFieldSpec(name="u_mag", quantity="U", location="node", invariant="magnitude"),
                ResultFieldSpec(name="s_mises", quantity="S", location="node", invariant="mises"),
            ]
        }
    )


def test_result_fields_select_magnitude_and_mises() -> None:
    extracted = attach_case_result_fields(
        {
            "fields": {
                "displacement": {"location": "node", "unit": "mm", "values": {"1": [3, 4, 0]}},
                "stress": {"location": "node", "unit": "MPa", "values": {"1": [3, 0, 0, 0, 0, 0]}},
            }
        },
        _case(),
    )
    assert extracted["requested_fields"]["u_mag"]["values"] == {"1": 5.0}
    assert extracted["requested_fields"]["s_mises"]["values"]["1"] == pytest.approx(3.0)
    assert extracted["requested_fields"]["u_mag"]["source"] == "fields.displacement"
    assert "ResultFieldSpec" in extracted["requested_fields"]["u_mag"]["derivation"]
    assert len(extracted["result_steps"]) == 1
    assert extracted["result_steps"][0]["step_id"] == "step-1"


def test_result_fields_include_stable_mesh_digest() -> None:
    case = _case()
    extracted = attach_case_result_fields(
        {
            "nodes": {"2": [1.0, 0.0, 0.0], "1": [0.0, 0.0, 0.0]},
            "elements": {"10": ["1", "2"]},
            "fields": {
                "displacement": {
                    "location": "node",
                    "values": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
                },
                "stress": {
                    "location": "node",
                    "values": {"1": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
                },
            },
        },
        case,
    )

    assert len(extracted["mesh_digest"]) == 64
    assert extracted["mesh_digest"].islower()


def test_result_fields_include_separate_physical_case_digest() -> None:
    case = _case()
    extracted = attach_case_result_fields(
        {
            "fields": {
                "displacement": {"location": "node", "values": {"1": [0.0, 0.0, 0.0]}},
                "stress": {
                    "location": "node",
                    "values": {"1": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
                },
            }
        },
        case,
    )

    assert extracted["case_digest"] == compute_case_digest(case)
    assert extracted["physical_case_digest"] == compute_physical_case_digest(case)

    alternate = case.model_copy(
        update={
            "result_fields": [
                field.model_copy(update={"location": "integration_point"})
                for field in case.result_fields
            ]
        }
    )
    assert compute_case_digest(alternate) != compute_case_digest(case)
    assert compute_physical_case_digest(alternate) == compute_physical_case_digest(case)


def test_result_fields_reject_declared_mesh_digest_mismatch() -> None:
    with pytest.raises(SolverError, match="mesh_digest"):
        attach_case_result_fields(
            {
                "mesh_digest": "0" * 64,
                "nodes": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
                "elements": {"10": ["1", "2"]},
                "fields": {
                    "displacement": {
                        "location": "node",
                        "values": {"1": [0.0, 0.0, 0.0]},
                    },
                    "stress": {
                        "location": "node",
                        "values": {"1": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
                    },
                },
            },
            _case(),
        )


def test_result_fields_reject_incomplete_multistep_history() -> None:
    case = _case().model_copy(
        update={
            "load_steps": [
                LoadStepSpec(step_id="step-1", sequence=1, result_fields=["u_mag"]),
                LoadStepSpec(step_id="step-2", sequence=2, result_fields=["s_mises"]),
            ]
        }
    )
    with pytest.raises(SolverError, match="多步结果缺少完整分析步字段"):
        attach_case_result_fields(
            {
                "fields": {
                    "displacement": {
                        "location": "node",
                        "values": {"1": [3, 4, 0]},
                    },
                    "stress": {
                        "location": "node",
                        "values": {"1": [3, 0, 0, 0, 0, 0]},
                    },
                },
                "field_history": [
                    {
                        "step_index": 1,
                        "displacement": {
                            "location": "node",
                            "values": {"1": [3, 4, 0]},
                        },
                        "stress": {
                            "location": "node",
                            "values": {"1": [3, 0, 0, 0, 0, 0]},
                        },
                    }
                ],
            },
            case,
        )


def test_result_fields_select_strain_volume_and_global_energy() -> None:
    case = _case().model_copy(
        update={
            "result_fields": [
                ResultFieldSpec(name="strain", quantity="E", location="integration_point"),
                ResultFieldSpec(name="volume", quantity="EVOL", location="element"),
                ResultFieldSpec(name="energy", quantity="ENER", location="global"),
            ]
        }
    )
    extracted = attach_case_result_fields(
        {
            "fields": {
                "strain": {
                    "location": "integration_point",
                    "values": {"1@ip1": [0.01, 0.0, 0.0]},
                },
                "volume": {"location": "element", "values": {"1": 8000.0}},
                "energy": {"location": "global", "values": {"ALLIE": 2.5}},
            }
        },
        case,
    )
    assert extracted["requested_fields"]["strain"]["values"]["1@ip1"] == [0.01, 0.0, 0.0]
    assert extracted["requested_fields"]["volume"]["values"] == {"1": 8000.0}
    assert extracted["requested_fields"]["energy"]["values"] == {"ALLIE": 2.5}


def test_required_result_field_missing_is_a_solver_failure() -> None:
    with pytest.raises(SolverError, match="所需的 S 场不存在"):
        attach_case_result_fields(
            {"fields": {"displacement": {"values": {"1": [1, 0, 0]}}}},
            _case(),
        )


def test_required_result_field_with_empty_values_is_a_solver_failure() -> None:
    with pytest.raises(SolverError, match="stress 场没有任何值"):
        attach_case_result_fields(
            {
                "fields": {
                    "displacement": {
                        "location": "node",
                        "values": {"1": [1, 0, 0]},
                    },
                    "stress": {"location": "node", "values": {}},
                }
            },
            _case(),
        )


def test_result_field_rejects_backend_location_mismatch() -> None:
    with pytest.raises(SolverError, match="请求位置 node"):
        attach_case_result_fields(
            {
                "fields": {
                    "displacement": {
                        "location": "element",
                        "values": {"1": [1, 0, 0]},
                    }
                }
            },
            _case(),
        )


def test_result_field_rejects_backend_unit_mismatch() -> None:
    case = _case().model_copy(
        update={
            "result_fields": [
                ResultFieldSpec(
                    name="u_mag",
                    quantity="U",
                    location="node",
                    invariant="magnitude",
                    unit="mm",
                )
            ]
        }
    )
    with pytest.raises(SolverError, match="请求单位 mm"):
        attach_case_result_fields(
            {
                "fields": {
                    "displacement": {
                        "location": "node",
                        "unit": "m",
                        "values": {"1": [0.001, 0.0, 0.0]},
                    }
                }
            },
            case,
        )


def test_result_field_rejects_missing_backend_unit_when_requested() -> None:
    case = _case().model_copy(
        update={
            "result_fields": [
                ResultFieldSpec(
                    name="u_mag",
                    quantity="U",
                    location="node",
                    invariant="magnitude",
                    unit="mm",
                )
            ]
        }
    )
    with pytest.raises(SolverError, match="后端只提供 未声明"):
        attach_case_result_fields(
            {
                "fields": {
                    "displacement": {
                        "location": "node",
                        "values": {"1": [1.0, 0.0, 0.0]},
                    }
                }
            },
            case,
        )


def test_step_results_only_contain_fields_declared_by_that_step() -> None:
    case = _case()
    case = case.model_copy(
        update={
            "load_steps": [
                LoadStepSpec(
                    step_id="step-1",
                    sequence=1,
                    result_fields=["u_mag"],
                ),
                LoadStepSpec(
                    step_id="step-2",
                    sequence=2,
                    load_scale=0.5,
                    result_fields=["s_mises"],
                ),
            ]
        }
    )
    extracted = attach_case_result_fields(
        {
            "fields": {
                "displacement": {"location": "node", "values": {"1": [3, 4, 0]}},
                "stress": {"location": "node", "values": {"1": [3, 0, 0, 0, 0, 0]}},
            },
            "field_history": [
                {
                    "step_index": 1,
                    "displacement": {"location": "node", "values": {"1": [3, 4, 0]}},
                    "stress": {"location": "node", "values": {"1": [3, 0, 0, 0, 0, 0]}},
                },
                {
                    "step_index": 2,
                    "displacement": {"location": "node", "values": {"1": [1, 0, 0]}},
                    "stress": {"location": "node", "values": {"1": [4, 0, 0, 0, 0, 0]}},
                },
            ],
        },
        case,
    )

    assert list(extracted["step_results"][0]["fields"]) == ["u_mag"]
    assert list(extracted["step_results"][1]["fields"]) == ["s_mises"]


def test_named_step_history_follows_declared_sequence() -> None:
    case = _case().model_copy(
        update={
            "load_steps": [
                LoadStepSpec(step_id="step-1", sequence=1, result_fields=["u_mag"]),
                LoadStepSpec(step_id="step-2", sequence=2, result_fields=["s_mises"]),
            ]
        }
    )
    extracted = attach_case_result_fields(
        {
            "fields": {
                "displacement": {"location": "node", "values": {"1": [3, 4, 0]}},
                "stress": {"location": "node", "values": {"1": [3, 0, 0, 0, 0, 0]}},
            },
            "field_history": [
                {
                    "step_name": "step-2",
                    "frame_index": 0,
                    "stress": {
                        "location": "node",
                        "values": {"1": [3, 0, 0, 0, 0, 0]},
                    },
                },
                {
                    "step_name": "step-1",
                    "frame_index": 0,
                    "displacement": {
                        "location": "node",
                        "values": {"1": [3, 4, 0]},
                    },
                },
            ],
        },
        case,
    )

    assert [item["step_id"] for item in extracted["step_results"]] == ["step-1", "step-2"]


def test_mapped_fields_use_element_centroids_and_preserve_native_fields() -> None:
    case = SimulationCase.from_model_params(tc03_model_params(), provenance_confidence=1.0)
    extracted = attach_mapped_result_fields(
        {
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "unit": "MPa",
                    "values": {
                        "10@ip1": [10.0, 2.0, 0.0, 0.0, 0.0, 0.0],
                        "10@ip2": [12.0, 2.0, 0.0, 0.0, 0.0, 0.0],
                    },
                },
                "strain": {
                    "location": "integration_point",
                    "values": {
                        "10@ip1": [0.1, 0.0, 0.0],
                        "10@ip2": [0.3, 0.0, 0.0],
                    },
                },
                "volume": {"location": "element", "values": {"10": 20.0}},
                "strain_energy_density": {
                    "location": "integration_point",
                    "values": {"10@ip1": 1.0, "10@ip2": 3.0},
                },
            },
            "elements": {"10": ["1", "2"]},
            "element_centroids": {"10": [5.0, 0.0, 0.0]},
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [10.0, 0.0, 0.0]},
        },
        case,
    )

    assert extracted["fields"]["stress"]["values"]["10@ip1"][0] == 10.0
    assert extracted["mapped_fields"]["stress_sxx"]["location"] == "element_centroid"
    assert extracted["mapped_fields"]["stress_sxx"]["values"] == {"10": 11.0}
    assert extracted["mapped_fields"]["strain_exx"]["values"] == {"10": 0.2}
    assert extracted["mapped_fields"]["volume"]["values"] == {"10": 20.0}
    assert extracted["mapped_fields"]["strain_energy_density"]["values"] == {"10": 2.0}
    assert extracted["mapped_fields"]["stress_sxx"]["source"] == "fields.stress"
    assert "单元质心" in extracted["mapped_fields"]["stress_sxx"]["derivation"]
    assert extracted["mapped_fields"]["stress_sxx"]["source_count"] == 2
    assert extracted["mapped_fields"]["stress_sxx"]["target_count"] == 1
    assert extracted["mapped_fields"]["stress_sxx"]["mapped_count"] == 1
    assert extracted["mapped_fields"]["stress_sxx"]["coverage"] == 1.0
    assert extracted["mapped_fields"]["stress_sxx"]["complete"] is True
    assert extracted["mapped_fields"]["stress_sxx"]["source_location"] == "integration_point"


def test_mapped_beam_volume_uses_mesh_nodes_when_native_volume_is_absent() -> None:
    case = SimulationCase.from_model_params(tc01_model_params(), provenance_confidence=1.0)
    extracted = attach_mapped_result_fields(
        {
            "fields": {},
            "elements": {"1": ["1", "2"]},
            "element_centroids": {"1": [5.0, 0.0, 0.0]},
            "mesh_nodes": {"1": [0.0, 0.0, 0.0], "2": [10.0, 0.0, 0.0]},
        },
        case,
    )

    assert extracted["mapped_fields"]["volume"]["values"] == {"1": 8000.0}
    assert extracted["mapped_fields"]["volume"]["source"] == "mesh_nodes+case.geometry"


def test_mapped_beam_volume_accepts_abaqus_node_key() -> None:
    case = SimulationCase.from_model_params(tc01_model_params(), provenance_confidence=1.0)
    extracted = attach_mapped_result_fields(
        {
            "fields": {},
            "elements": {"1": ["1", "2"]},
            "element_centroids": {"1": [5.0, 0.0, 0.0]},
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [10.0, 0.0, 0.0]},
        },
        case,
    )

    assert extracted["mapped_fields"]["volume"]["values"] == {"1": 8000.0}


def test_mapped_solid_field_does_not_use_beam_axis_fallback_for_missing_nodes() -> None:
    case = SimulationCase.from_model_params(tc03_model_params(), provenance_confidence=1.0)
    extracted = attach_mapped_result_fields(
        {
            "fields": {
                "stress": {
                    "location": "node",
                    "unit": "MPa",
                    "values": {"1": [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
                }
            },
            "elements": {"10": ["1", "2"]},
            "element_centroids": {"10": [0.5, 0.0, 0.0]},
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
        },
        case,
    )

    assert "mapped_fields" not in extracted


def test_mapped_field_retains_partial_coverage_instead_of_claiming_complete_mapping() -> None:
    case = SimulationCase.from_model_params(tc03_model_params(), provenance_confidence=1.0)
    extracted = attach_mapped_result_fields(
        {
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "unit": "MPa",
                    "values": {"10@ip1": [10.0, 0.0, 0.0]},
                }
            },
            "elements": {"10": ["1", "2"], "11": ["2", "3"]},
            "element_centroids": {"10": [0.5, 0.0, 0.0], "11": [1.5, 0.0, 0.0]},
        },
        case,
    )

    field = extracted["mapped_fields"]["stress_sxx"]
    assert field["values"] == {"10": 10.0}
    assert field["source_count"] == 1
    assert field["target_count"] == 2
    assert field["mapped_count"] == 1
    assert field["coverage"] == 0.5
    assert field["complete"] is False


def test_mapped_step_fields_follow_declared_step_sequence_and_frame_order() -> None:
    base = SimulationCase.from_model_params(tc03_model_params(), provenance_confidence=1.0)
    case = base.model_copy(
        update={
            "load_steps": [
                LoadStepSpec(step_id="step-1", sequence=1),
                LoadStepSpec(step_id="step-2", sequence=2),
            ]
        }
    )
    extracted = attach_mapped_result_fields(
        {
            "fields": {},
            "elements": {"10": ["1", "2"]},
            "element_centroids": {"10": [0.5, 0.0, 0.0]},
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
            "field_history": [
                {
                    "step_name": "step-2",
                    "frame_index": 0,
                    "stress": {
                        "location": "integration_point",
                        "unit": "MPa",
                        "values": {"10@ip1": [20.0, 0.0, 0.0]},
                    },
                },
                {
                    "step_name": "step-1",
                    "frame_index": 0,
                    "stress": {
                        "location": "integration_point",
                        "unit": "MPa",
                        "values": {"10@ip1": [10.0, 0.0, 0.0]},
                    },
                },
                {
                    "step_name": "step-2",
                    "frame_index": 1,
                    "stress": {
                        "location": "integration_point",
                        "unit": "MPa",
                        "values": {"10@ip1": [25.0, 0.0, 0.0]},
                    },
                },
            ],
        },
        case,
    )

    steps = extracted["mapped_step_fields"]
    assert [item["step_id"] for item in steps] == ["step-1", "step-2"]
    assert [frame["frame_index"] for frame in steps[1]["frames"]] == [0, 1]
    assert steps[0]["mapped_fields"]["stress_sxx"]["values"] == {"10": 10.0}
    assert steps[1]["frames"][1]["mapped_fields"]["stress_sxx"]["values"] == {"10": 25.0}
