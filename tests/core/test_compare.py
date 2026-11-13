from __future__ import annotations

import pytest

from mechagent.core.compare import (
    ComparisonTolerance,
    compare_backend_results,
    compare_backend_step_fields,
    derive_comparison_fields,
    evaluate_reaction_balance,
)
from mechagent.core.models import GeometrySpec, GeometryType
from mechagent.core.results import compute_mesh_digest
from mechagent.core.validation import tc01_model_params, tc02_model_params, tc03_model_params


def test_backend_comparison_rejects_case_fingerprint_mismatch() -> None:
    left = {
        "case_digest": "a" * 64,
        "requested_fields": {
            "u": {"location": "node", "values": {"1": 1.0}},
        },
    }
    right = {
        "case_digest": "b" * 64,
        "requested_fields": {
            "u": {"location": "node", "values": {"1": 1.0}},
        },
    }

    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
    )

    assert result.status == "failed"
    assert result.differences[0]["reason"] == "case_digest_mismatch"


def test_backend_comparison_accepts_different_full_contracts_with_same_physical_digest() -> None:
    left = {
        "case_digest": "a" * 64,
        "physical_case_digest": "p" * 64,
        "mapped_fields": {
            "stress_sxx": {
                "location": "element_centroid",
                "unit": "MPa",
                "values": {"1": 10.0},
                "coverage": 1.0,
                "complete": True,
            }
        },
        "element_centroids": {"1": [0.5, 0.0, 0.0]},
    }
    right = {
        "case_digest": "b" * 64,
        "physical_case_digest": "p" * 64,
        "mapped_fields": {
            "stress_sxx": {
                "location": "element_centroid",
                "unit": "MPa",
                "values": {"2": 10.0},
                "coverage": 1.0,
                "complete": True,
            }
        },
        "element_centroids": {"2": [0.5, 0.0, 0.0]},
    }

    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        field_source="mapped_fields",
    )

    assert result.status == "passed"


def test_backend_comparison_rejects_physical_case_digest_mismatch() -> None:
    result = compare_backend_results(
        {
            "case_digest": "a" * 64,
            "physical_case_digest": "p" * 64,
            "requested_fields": {"u": {"values": {"1": 1.0}}},
        },
        {
            "case_digest": "b" * 64,
            "physical_case_digest": "q" * 64,
            "requested_fields": {"u": {"values": {"1": 1.0}}},
        },
        left_backend="calculix",
        right_backend="abaqus",
    )

    assert result.status == "failed"
    assert result.differences[0]["reason"] == "physical_case_digest_mismatch"


@pytest.mark.parametrize(
    ("key", "left_value", "right_value", "reason"),
    [
        (
            "units",
            {"length": "mm", "force": "N"},
            {"length": "m", "force": "N"},
            "units_mismatch",
        ),
        (
            "coordinate_system",
            {"name": "global", "axes": ["x", "y", "z"]},
            {"name": "local", "axes": ["x", "y", "z"]},
            "coordinate_system_mismatch",
        ),
    ],
)
def test_backend_comparison_rejects_result_contract_mismatch(
    key: str, left_value: dict[str, object], right_value: dict[str, object], reason: str
) -> None:
    result = compare_backend_results(
        {key: left_value, "requested_fields": {"u": {"values": {"1": 1.0}}}},
        {key: right_value, "requested_fields": {"u": {"values": {"1": 1.0}}}},
        left_backend="calculix",
        right_backend="abaqus",
    )

    assert result.status == "failed"
    assert result.differences[0]["reason"] == reason


def test_backend_comparison_rejects_one_sided_result_contract_metadata() -> None:
    result = compare_backend_results(
        {
            "units": {"length": "mm"},
            "requested_fields": {"u": {"values": {"1": 1.0}}},
        },
        {"requested_fields": {"u": {"values": {"1": 1.0}}}},
        left_backend="calculix",
        right_backend="abaqus",
    )

    assert result.status == "failed"
    assert result.differences[0]["reason"] == "units_missing"


def test_backend_comparison_passes_within_tolerance() -> None:
    left = {"requested_fields": {"u": {"values": {"1": [1.0, 0.0, 0.0]}}}}
    right = {"requested_fields": {"u": {"values": {"1": [1.0001, 0.0, 0.0]}}}}
    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-9),
    )
    assert result.status == "passed"
    assert result.differences == []


def test_backend_comparison_rejects_requested_field_location_mismatch() -> None:
    result = compare_backend_results(
        {"requested_fields": {"u": {"location": "node", "unit": "mm", "values": {"1": 1.0}}}},
        {"requested_fields": {"u": {"location": "element", "unit": "mm", "values": {"1": 1.0}}}},
        left_backend="calculix",
        right_backend="abaqus",
    )

    assert result.status == "failed"
    assert result.alignment == {"u": "contract-mismatch"}
    assert result.differences == [
        {
            "field": "u",
            "reason": "field_location_mismatch",
            "left_location": "node",
            "right_location": "element",
        }
    ]
    assert result.field_results["u"].status == "failed"
    assert result.field_results["u"].reason == "field_location_mismatch"


def test_backend_comparison_reports_missing_and_large_difference() -> None:
    left = {"requested_fields": {"u": {"values": {"1": 1.0}}, "s": {"values": {"1": 2.0}}}}
    right = {"requested_fields": {"u": {"values": {"1": 2.0}}}}
    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
    )
    assert result.status == "failed"
    assert "s" in result.missing_fields
    assert result.differences[0]["field"] == "u"


def test_backend_comparison_without_requested_fields_is_unverified() -> None:
    result = compare_backend_results({}, {}, left_backend="a", right_backend="b")
    assert result.status == "unverified"


def test_backend_comparison_rejects_non_numeric_values() -> None:
    with pytest.raises(ValueError, match="有限数字"):
        compare_backend_results(
            {"requested_fields": {"u": {"values": {"1": "bad"}}}},
            {"requested_fields": {"u": {"values": {"1": 1.0}}}},
            left_backend="a",
            right_backend="b",
        )


def test_backend_comparison_uses_field_summary_when_mesh_labels_differ() -> None:
    result = compare_backend_results(
        {
            "requested_fields": {
                "u": {
                    "values": {"a": 1.0, "b": 3.0},
                    "summary": {"count": 2.0, "max_abs": 3.0, "mean": 2.0},
                }
            }
        },
        {
            "requested_fields": {
                "u": {
                    "values": {"x": 1.0, "y": 3.0001},
                    "summary": {"count": 2.0, "max_abs": 3.0001, "mean": 2.00005},
                }
            }
        },
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-9),
    )

    assert result.status == "passed"
    assert all("summary[" in field for field in result.compared_fields)


def test_backend_comparison_aligns_node_fields_by_coordinate() -> None:
    result = compare_backend_results(
        {
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
            "requested_fields": {
                "u": {
                    "location": "node",
                    "values": {"1": [0.0, 2.0, 0.0], "2": [0.0, 4.0, 0.0]},
                }
            },
        },
        {
            "nodes": {"10": [1.0, 0.0, 0.0], "20": [0.0, 0.0, 0.0]},
            "requested_fields": {
                "u": {
                    "location": "node",
                    "values": {"10": [0.0, 4.0001, 0.0], "20": [0.0, 2.0, 0.0]},
                }
            },
        },
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-9),
    )

    assert result.status == "passed"
    assert result.alignment == {"u": "node-coordinate"}
    assert all("<->" in field for field in result.compared_fields)


def test_backend_comparison_reconstructs_beam_centerline_from_raw_vectors() -> None:
    result = compare_backend_results(
        {
            "nodes": {
                "101": [0.0, 0.0, -1.0],
                "102": [0.0, 0.0, 1.0],
                "201": [20.0, 0.0, -1.0],
                "202": [20.0, 0.0, 1.0],
            },
            "fields": {
                "displacement": {
                    "values": {
                        "101": [0.0, -0.1, -0.02],
                        "102": [0.0, -0.1, 0.02],
                        "201": [0.0, -1.0, -0.02],
                        "202": [0.0, -1.0, 0.02],
                    }
                }
            },
            "requested_fields": {
                "displacement": {
                    "location": "node",
                    "selector": "magnitude",
                    "values": {"101": 0.10198, "102": 0.10198, "201": 1.0002, "202": 1.0002},
                }
            },
        },
        {
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [20.0, 0.0, 0.0]},
            "fields": {"displacement": {"values": {"1": [0.0, -0.1, 0.0], "2": [0.0, -1.0, 0.0]}}},
            "requested_fields": {
                "displacement": {
                    "location": "node",
                    "selector": "magnitude",
                    "values": {"1": 0.1, "2": 1.0},
                }
            },
        },
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-9),
    )

    assert result.status == "passed"
    assert result.alignment == {"displacement": "line-coordinate-centerline"}
    assert result.differences == []


def test_backend_comparison_marks_raw_fields_at_different_locations_unverified() -> None:
    result = compare_backend_results(
        {
            "fields": {
                "stress": {
                    "location": "node",
                    "values": {"1": [10.0, -2.0], "2": [4.0, 1.0]},
                },
                "energy": {"location": "element", "values": {"1": 12.0}},
            }
        },
        {
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "values": {"10@ip1": [10.0001, -2.0], "11@ip1": [4.0, 1.0]},
                },
                "energy": {"location": "global", "values": {"ALLIE": 12.0001}},
            }
        },
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-3),
        field_source="fields",
    )

    assert result.status == "unverified"
    assert result.field_source == "fields"
    assert result.unverified_fields == ["energy", "stress"]
    assert result.alignment == {"energy": "unverified", "stress": "unverified"}
    assert result.field_results["stress"].status == "unverified"
    assert result.field_results["stress"].reason == "field_location_mismatch"


def test_backend_comparison_aligns_exact_integration_points_with_mesh_digest() -> None:
    mesh = {
        "nodes": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
        "elements": {"10": ["1", "2"]},
    }
    mesh["mesh_digest"] = compute_mesh_digest(mesh)
    left = {
        **mesh,
        "fields": {
            "stress": {
                "location": "integration_point",
                "unit": "MPa",
                "values": {"10@ip1": [10.0, 0.0, 0.0]},
            }
        },
    }
    right = {
        **mesh,
        "fields": {
            "stress": {
                "location": "integration_point",
                "unit": "MPa",
                "values": {"10@ip1": [10.0001, 0.0, 0.0]},
            }
        },
    }

    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        field_source="fields",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-3),
    )

    assert result.status == "passed"
    assert result.alignment == {"stress": "integration-point-key"}


def test_backend_comparison_keeps_integration_points_unverified_without_mesh_digest() -> None:
    result = compare_backend_results(
        {
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "unit": "MPa",
                    "values": {"10@ip1": [10.0, 0.0, 0.0]},
                }
            }
        },
        {
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "unit": "MPa",
                    "values": {"10@ip1": [10.0, 0.0, 0.0]},
                }
            }
        },
        left_backend="calculix",
        right_backend="abaqus",
        field_source="fields",
    )

    assert result.status == "unverified"
    assert result.unverified_fields == ["stress"]


def test_backend_comparison_rejects_invalid_mesh_digest_provenance() -> None:
    mesh = {
        "nodes": {"1": [0.0, 0.0, 0.0], "2": [1.0, 0.0, 0.0]},
        "elements": {"10": ["1", "2"]},
        "mesh_digest": "0" * 64,
    }
    result = compare_backend_results(
        {
            **mesh,
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "unit": "MPa",
                    "values": {"10@ip1": [10.0, 0.0, 0.0]},
                }
            },
        },
        {
            **mesh,
            "fields": {
                "stress": {
                    "location": "integration_point",
                    "unit": "MPa",
                    "values": {"10@ip1": [10.0, 0.0, 0.0]},
                }
            },
        },
        left_backend="calculix",
        right_backend="abaqus",
        field_source="fields",
    )

    assert result.status == "unverified"
    assert result.unverified_fields == ["stress"]


def test_derived_comparison_fields_use_common_physical_semantics() -> None:
    left = {
        "nodes": {"1": [0.0, 0.0, 0.0]},
        "fields": {
            "stress": {"values": {"1": [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]}},
            "reaction_force": {"values": {"1": [-100.0, 0.0, 0.0]}},
        },
    }
    right = {
        "nodes": {"10": [0.0, 0.0, 0.0]},
        "fields": {
            "stress": {"values": {"10@ip1": [10.0001, 0.0, 0.0, 0.0, 0.0, 0.0]}},
            "reaction_force": {"values": {"10": [-100.0001, 0.0, 0.0]}},
        },
    }
    left["comparison_fields"] = derive_comparison_fields(
        left, elastic_modulus=210000.0, poisson_ratio=0.3
    )
    right["comparison_fields"] = derive_comparison_fields(
        right, elastic_modulus=210000.0, poisson_ratio=0.3
    )
    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-3),
        field_source="comparison_fields",
    )

    assert result.status == "passed"
    assert set(result.alignment) == {
        "reaction_resultant",
        "strain_energy_density",
        "stress_max_abs",
    }


def test_reaction_balance_passes_for_concentrated_force() -> None:
    result = evaluate_reaction_balance(
        {
            "success": True,
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [100.0, 0.0, 0.0]},
            "fields": {"reaction_force": {"values": {"1": [0.0, 1000.0, 0.0]}}},
        },
        tc01_model_params(),
        tolerance=ComparisonTolerance(relative=1.0e-6, absolute=1.0e-6),
    )
    assert result.status == "passed"
    assert result.applied_resultant == (0.0, -1000.0, 0.0)
    assert result.max_absolute_error == 0.0


def test_reaction_balance_supports_known_pressure_area() -> None:
    result = evaluate_reaction_balance(
        {
            "success": True,
            "nodes": {"1": [0.0, 0.0, 0.0], "2": [200.0, 0.0, 0.0]},
            "fields": {"reaction_force": {"values": {"1": [-4000.0, 0.0, 0.0]}}},
        },
        tc03_model_params(),
    )
    assert result.status == "passed"
    assert result.applied_resultant == (4000.0, 0.0, 0.0)


def test_reaction_balance_sums_all_supported_plate_edges() -> None:
    result = evaluate_reaction_balance(
        {
            "success": True,
            "nodes": {
                "1": [0.0, 0.0, 0.0],
                "2": [300.0, 0.0, 0.0],
                "3": [300.0, 200.0, 0.0],
                "4": [0.0, 200.0, 0.0],
            },
            "fields": {
                "reaction_force": {
                    "values": {
                        "1": [0.0, 0.0, 150.0],
                        "2": [0.0, 0.0, 150.0],
                        "3": [0.0, 0.0, 150.0],
                        "4": [0.0, 0.0, 150.0],
                    }
                }
            },
        },
        tc02_model_params(),
    )

    assert result.status == "passed"
    assert result.applied_resultant == (0.0, 0.0, -600.0)
    assert result.reaction_resultant == (0.0, 0.0, 600.0)


def test_reaction_balance_keeps_unknown_load_area_unverified() -> None:
    result = evaluate_reaction_balance(
        {"success": True, "fields": {}},
        tc03_model_params().model_copy(
            update={"geometry": GeometrySpec(type=GeometryType.SOLID, dimensions={"length": 200.0})}
        ),
    )
    assert result.status == "unverified"
    assert result.reason is not None


def test_reaction_balance_rejects_partial_solver_result() -> None:
    result = evaluate_reaction_balance(
        {"fields": {"reaction_force": {"values": {"1": [0.0, 1000.0, 0.0]}}}},
        tc01_model_params(),
    )
    assert result.status == "unverified"
    assert result.reason is not None


def test_reaction_balance_rejects_incomplete_reaction_vectors() -> None:
    result = evaluate_reaction_balance(
        {
            "success": True,
            "nodes": {"1": [0.0, 0.0, 0.0]},
            "fields": {"reaction_force": {"values": {"1": [1000.0]}}},
        },
        tc01_model_params(),
    )
    assert result.status == "unverified"


def test_mapped_fields_align_by_element_centroid_coordinates() -> None:
    left = {
        "mapped_fields": {
            "stress_sxx": {
                "location": "element_centroid",
                "unit": "MPa",
                "values": {"10": 100.0},
            }
        },
        "element_centroids": {"10": [5.0, 0.0, 0.0]},
    }
    right = {
        "mapped_fields": {
            "stress_sxx": {
                "location": "element_centroid",
                "unit": "MPa",
                "values": {"42": 100.05},
            }
        },
        "element_centroids": {"42": [5.0, 0.0, 0.0]},
    }

    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        field_source="mapped_fields",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-6),
    )

    assert result.status == "passed"
    assert result.alignment == {"stress_sxx": "element-centroid-coordinate"}
    assert result.compared_fields == ["stress_sxx[10<->42]"]
    assert result.field_results["stress_sxx"].status == "passed"
    assert result.field_results["stress_sxx"].compared_count == 1
    assert result.field_results["stress_sxx"].alignment == "element-centroid-coordinate"


def test_mapped_fields_with_incomplete_coverage_are_unverified() -> None:
    left = {
        "mapped_fields": {
            "stress_sxx": {
                "location": "element_centroid",
                "unit": "MPa",
                "values": {"10": 100.0},
                "coverage": 0.5,
                "complete": False,
                "mapping": "integration-point-mean",
            }
        },
        "element_centroids": {"10": [5.0, 0.0, 0.0]},
    }
    right = {
        "mapped_fields": {
            "stress_sxx": {
                "location": "element_centroid",
                "unit": "MPa",
                "values": {"42": 100.0},
                "coverage": 1.0,
                "complete": True,
                "mapping": "integration-point-mean",
            }
        },
        "element_centroids": {"42": [5.0, 0.0, 0.0]},
    }

    result = compare_backend_results(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        field_source="mapped_fields",
    )

    assert result.status == "unverified"
    assert result.unverified_fields == ["stress_sxx"]
    assert result.field_results["stress_sxx"].status == "unverified"
    assert result.field_results["stress_sxx"].reason == "mapping_incomplete"
    assert result.field_results["stress_sxx"].left_coverage == 0.5


def test_multistep_mapped_fields_compare_each_frame() -> None:
    common = {
        "case_digest": "a" * 64,
        "units": {"length": "mm"},
        "coordinate_system": {"name": "global"},
        "element_centroids": {"1": [0.5, 0.0, 0.0]},
    }
    left = {
        **common,
        "mapped_step_fields": [
            {
                "step_id": "step-1",
                "sequence": 1,
                "frames": [
                    {
                        "frame_index": 0,
                        "mapped_fields": {
                            "stress_sxx": {
                                "location": "element_centroid",
                                "unit": "MPa",
                                "values": {"1": 10.0},
                                "coverage": 1.0,
                                "complete": True,
                            }
                        },
                    },
                    {
                        "frame_index": 1,
                        "mapped_fields": {
                            "stress_sxx": {
                                "location": "element_centroid",
                                "unit": "MPa",
                                "values": {"1": 20.0},
                                "coverage": 1.0,
                                "complete": True,
                            }
                        },
                    },
                ],
            }
        ],
    }
    right = {
        **common,
        "element_centroids": {"42": [0.5, 0.0, 0.0]},
        "mapped_step_fields": [
            {
                "step_id": "step-1",
                "sequence": 1,
                "frames": [
                    {
                        "frame_index": 0,
                        "mapped_fields": {
                            "stress_sxx": {
                                "location": "element_centroid",
                                "unit": "MPa",
                                "values": {"42": 10.001},
                                "coverage": 1.0,
                                "complete": True,
                            }
                        },
                    },
                    {
                        "frame_index": 1,
                        "mapped_fields": {
                            "stress_sxx": {
                                "location": "element_centroid",
                                "unit": "MPa",
                                "values": {"42": 20.001},
                                "coverage": 1.0,
                                "complete": True,
                            }
                        },
                    },
                ],
            }
        ],
    }

    result = compare_backend_step_fields(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
        tolerance=ComparisonTolerance(relative=1.0e-3, absolute=1.0e-3),
    )

    assert result.status == "passed"
    assert len(result.steps) == 2
    assert [item.frame_index for item in result.steps] == [0, 1]
    assert result.steps[0].comparison.field_results["stress_sxx"].status == "passed"


def test_multistep_comparison_rejects_missing_frame() -> None:
    left = {
        "mapped_step_fields": [
            {
                "step_id": "step-1",
                "frames": [
                    {"frame_index": 0, "mapped_fields": {"stress_sxx": {"values": {"1": 1.0}}}},
                    {"frame_index": 1, "mapped_fields": {"stress_sxx": {"values": {"1": 2.0}}}},
                ],
            }
        ],
        "element_centroids": {"1": [0.5, 0.0, 0.0]},
    }
    right = {
        "mapped_step_fields": [
            {
                "step_id": "step-1",
                "frames": [
                    {"frame_index": 0, "mapped_fields": {"stress_sxx": {"values": {"1": 1.0}}}},
                ],
            }
        ],
        "element_centroids": {"1": [0.5, 0.0, 0.0]},
    }

    result = compare_backend_step_fields(
        left,
        right,
        left_backend="calculix",
        right_backend="abaqus",
    )

    assert result.status == "failed"
    assert result.missing_frames == ["id:step-1[1]"]
