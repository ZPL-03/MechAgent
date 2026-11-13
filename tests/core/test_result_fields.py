from __future__ import annotations

import pytest

from mechagent.core import attach_case_result_fields, attach_mapped_result_fields
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
    assert len(extracted["result_steps"]) == 1
    assert extracted["result_steps"][0]["step_id"] == "step-1"


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
