from __future__ import annotations

import pytest

from mechagent.core import attach_case_result_fields
from mechagent.core.exceptions import SolverError
from mechagent.core.models import LoadStepSpec, ResultFieldSpec, SimulationCase
from mechagent.core.validation import tc01_model_params


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
