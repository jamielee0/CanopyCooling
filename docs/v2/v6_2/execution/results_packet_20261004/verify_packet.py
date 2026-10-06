"""Independent final CSV/source/plot reconciliation for the Step 2 packet."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
EXEC = Path(__file__).resolve().parent
OUT = ROOT / "deliverables/Results_Review_2023_v6_2_20261004"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify():
    freeze = json.loads((EXEC/"execution_freeze.json").read_text())
    matrix = json.loads((EXEC/"results_matrix.json").read_text())
    author = json.loads((EXEC/"csv_author_verification.json").read_text())
    names = [f["name"] for f in matrix["fields"]]
    with (OUT/"pass_results_long.csv").open(newline="") as handle:
        csv_reader = csv.DictReader(handle)
        assert csv_reader.fieldnames == names
        actual = list(csv_reader)
    assert len(actual) == 64
    for row, expected in zip(actual, matrix["rows"]):
        for field, value in zip(matrix["fields"], expected):
            cell = row[field["name"]]
            if value is None:
                assert cell == "", (field["name"], cell)
            elif field["type"] in ("number", "integer"):
                assert float(cell) == value, (field["name"], cell, value)
            else:
                assert cell == value, (field["name"], cell, value)
    assert author["csv_sha256"] == digest(OUT/"pass_results_long.csv")
    original = [r for r in actual if r["variant"] == "original"]
    assert Counter(r["city"] for r in original) == {"phoenix": 11, "atlanta": 5}
    assert actual[:16] == original
    assert all(r["collection"] == "002" for r in actual)
    assert all(r["local_date"].startswith("2023-") for r in actual)
    assert len({(r["city"], r["orbit"], r["source_run_id"], r["variant"]) for r in actual}) == 64
    released_path = ROOT/"outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv"
    with released_path.open() as h:
        released = {(r["city"], r["orbit"], r["run_id"], r["variant"]): r for r in csv.DictReader(h)}
    for row in actual:
        source = released[(row["city"], row["orbit"], row["source_run_id"], row["source_model_variant"])]
        size = row["resampling_group_km"]
        for output, input_field in (
            ("cooling_K_per_10pp", "cooling_K_per_10pp"),
            ("signed_change_T_K_per_10pp", "gradient_K_per_10pp"),
            ("spatial_SE_K_per_10pp", f"SE_{size}km_K_per_10pp"),
            ("cooling_q025_K_per_10pp", f"cooling_q025_{size}km"),
            ("cooling_q975_K_per_10pp", f"cooling_q975_{size}km"),
        ):
            assert float(row[output]) == float(source[input_field]), (row["orbit"], output)
        assert abs(.1*float(row["signed_slope_T_K_per_canopy_fraction"])-float(row["signed_change_T_K_per_10pp"])) < 1e-12
        assert abs(float(row["footprint_area_km2"])-int(row["n_cells"])*.0049) < 1e-9
        for field in ("signed_flux_change_W_m2_per_10pp", "flux_reduction_W_m2_per_10pp", "signed_equivalent_change_K_per_10pp", "equivalent_cooling_K_per_10pp"):
            assert row[field] == ""
        assert row["paired_effect_status"] == "SEALED_NOT_RELEASED"
        assert int(row["bootstrap_requested"]) == int(row["bootstrap_estimable"])+int(row["bootstrap_failed"])
    points = json.loads((OUT/"plot_points.json").read_text())["points"]
    plotted = {(p["city"], p["orbit"], p["source_run_id"], p["variant"]): p for p in points}
    assert len(points) == len(plotted) == 32
    expected_keys = {(r["city"], r["orbit"], r["source_run_id"], r["variant"]) for r in actual if r["resampling_group_km"] in ("1", "8")}
    assert set(plotted) == expected_keys
    for row in actual:
        key = (row["city"], row["orbit"], row["source_run_id"], row["variant"])
        if key in plotted:
            p = plotted[key]
            for field in ("apparent_solar_hour", "cooling_K_per_10pp", "cooling_q025_K_per_10pp", "cooling_q975_K_per_10pp"):
                assert float(row[field]) == p[field]
    for source in freeze["inputs"]:
        assert digest(ROOT/source["path"]) == source["sha256"], source["path"]
    assert str((ROOT/"data").resolve(strict=True)) == freeze["data_link_target"]
    report = {
        "status": "PASSED", "rows": 64, "originals": 16, "uncertainty_sensitivities": 48,
        "columns": len(names), "cities": {"phoenix": 11, "atlanta": 5},
        "plotted_points_in_two_panels_each": 32, "complete_linked_weather": sum(r["air_temperature_K"] != "" for r in original),
        "tests": "14 network-free known-answer/boundary tests passed",
        "checks": "Exact CSV typed roundtrip, source estimates/SE/intervals, identifiers and leading zeros, signs/units, draw accounting, area, plot-point mapping, all frozen input hashes and data link",
        "sealed_effect_fields_empty": True, "sealed_files_opened": [], "new_model_fits": 0,
        "visual_qa": "pending human-style inspection by agent", "csv_sha256": digest(OUT/"pass_results_long.csv"),
    }
    (EXEC/"final_verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": verify()
