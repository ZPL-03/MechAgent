from __future__ import annotations

import pytest

from mechagent.core.compare import (
    ComparisonTolerance,
    compare_backend_results,
    derive_comparison_fields,
)


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
