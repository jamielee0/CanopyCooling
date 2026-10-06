"""Verify public-only Step3 tables, preservation and sealed permissions."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
EXEC = Path(__file__).resolve().parent
PUB = ROOT/"outputs/v6_2/scientific/spatial_scale_review_20261004"
SEALED = ROOT/"outputs/v6_2/sealed_coefficients/spatial_scale_review_20261004"
OUT = ROOT/"deliverables/Spatial_Scale_Review_2023_v6_2_20261004"


def sha(path):
    with path.open("rb") as h: return hashlib.file_digest(h, "sha256").hexdigest()


def verify():
    freeze = json.loads((EXEC/"execution_freeze.json").read_text())
    data = json.loads((PUB/"public_table_matrices.json").read_text())
    numerical = json.loads((PUB/"validation.json").read_text())
    author = json.loads((EXEC/"csv_author_verification.json").read_text())
    table_reports = []
    for record in author["tables"]:
        name = record["file"]
        assert sha(PUB/name)==sha(OUT/name)==record["sha256"]
        with (OUT/name).open(newline="") as h:
            r = csv.reader(h); rows=list(r)
        expected = data[name]
        assert rows[0] == expected["headers"] and len(rows)-1==len(expected["rows"])
        for row, values in zip(rows[1:], expected["rows"]):
            assert len(row)==len(values)
            for cell, value in zip(row, values):
                if value is None: assert cell==""
                elif isinstance(value, (float, int)): assert float(cell)==value
                else: assert cell==str(value)
        assert not set(rows[0]).intersection(("point", "q025", "q975", "cooling_change", "signed_difference", "CE_T", "CE_M_equivalent"))
        table_reports.append(dict(file=name, rows=len(rows)-1, typed_roundtrip="exact", new_effect_fields=False))
    for src in freeze["inputs"]: assert sha(ROOT/src["path"])==src["sha256"], "Frozen source changed"
    adjustments=json.loads((EXEC/"implementation_adjustments.json").read_text())
    assert adjustments["scientific_design_changed"] is False and adjustments["arbitrary_pickle_globals_allowed"] is False
    final_codes={r["path"]:r for r in adjustments["versions"]}
    for src in freeze["code_at_freeze"]:
        recorded=final_codes[src["path"]]
        assert sha(ROOT/recorded["initial_archive"])==src["sha256"]==recorded["initial_sha256"], "Initial frozen code not preserved"
        assert sha(ROOT/src["path"])==recorded["final_sha256"], "Unrecorded code change"
    assert str((ROOT/"data").resolve(strict=True))==freeze["data_link_target"]
    assert numerical["original_and_common_point_recoveries"]==11
    assert numerical["joint_difference_configurations"]==22
    assert numerical["joint_requested"]==22000
    assert numerical["joint_estimable"]+numerical["joint_failed"]==22000
    assert numerical["fixed_registration_pairs"]==24 and numerical["available_support_points"]==44
    assert numerical["paired_scale_configurations"]==32
    assert numerical["empirical_time_comparisons"]==numerical["raw_thermal_raster_reads"]==0
    assert numerical["displayed_new_effects"] is False and numerical["agreement_ruling"] is False
    support = data["footprint_and_reference_support.csv"]
    records = [dict(zip(support["headers"], row)) for row in support["rows"]]
    phoenix = [r for r in records if r["city"]=="phoenix"]
    assert len(records)==16 and len(phoenix)==11
    assert all(r["common_all11_cells"]==196090 for r in phoenix)
    for r in phoenix:
        assert r["original_cells"]==r["common_all11_cells"]+r["excluded_cells"]
        assert r["common_all11_retained_fraction"]==196090/r["original_cells"]
        assert abs(r["common_all11_area_km2"]-960.841)<1e-9
    assert SEALED.stat().st_mode & 0o777==0o700
    sealed_files=list(SEALED.iterdir())
    assert all("SEALED" in p.name and p.stat().st_mode & 0o777==0o600 for p in sealed_files)
    assert not any("SEALED" in p.name for p in OUT.iterdir())
    access=json.loads((PUB/"access_record.json").read_text())
    assert not access["time_contrast_files_opened"]
    assert not any("time_contrasts" in r["path"] for r in access["accesses"])
    report = dict(status="PASSED_NUMERICAL_AND_BOUNDARY_CHECKS_VISUAL_QA_PENDING", tests=20,
        public_tables=table_reports, frozen_source_hashes=len(freeze["inputs"]), frozen_inputs_unchanged=True,
        initial_code_preserved=True, recorded_repairs_verified=True, scientific_design_unchanged=True,
        native_common_identity_and_areas=True, targeted_point_recoveries=11, joint_draw_accounting=22000,
        fixed_registration_pairing_validated=24, available_support_difference_intervals="unavailable; no inferred pairing",
        paired_scale_configurations=32, all_new_effects_sealed=True, sealed_file_count=len(sealed_files),
        file_permissions_and_public_export_boundary=True, empirical_time_files_opened=0,
        scientific_agreement_ruling=False, scale_tolerance=None)
    (EXEC/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__ == "__main__": verify()
