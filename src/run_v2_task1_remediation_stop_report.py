#!/usr/bin/env python3
"""Write the canonical Task-1 stop after the D0033 remediation audit.

This reporter is deliberately fail-closed.  It accepts the exhaustive asset
census only when its separate scientific-eligibility fields record the
cloud-conditioned view gate discovered by the full pair diagnostic.  It never
opens an ECOSTRESS thermal layer or creates an HRRR request manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "data/processed/v2/task1/step2_quality_screening_exhaustive"
OUTPUT = ROOT / "data/processed/v2/task1/step2_remediation"
TASK1_GATE = ROOT / "data/processed/v2/task1/TASK1_GATE.md"
EXPECTED_STATUS = "STOP_CLOUD_CONDITIONED_VIEW_GATE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _load_and_validate() -> tuple[dict[str, object], pd.DataFrame]:
    validation_path = QUALITY / "cloud_exhaustive_validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    required = {
        "decision_id": "D0033",
        "complete": True,
        "candidate_seal_geometry_only": False,
        "candidate_view_mask_cloud_independent": False,
        "view_gate_cloud_conditioned": True,
        "scientific_gate_eligible": False,
        "gate_status": EXPECTED_STATUS,
        "canonical_status": EXPECTED_STATUS,
        "lst_opened": False,
        "holdout_status": "UNSELECTED",
    }
    disagreements = {
        key: {"expected": expected, "observed": validation.get(key)}
        for key, expected in required.items()
        if validation.get(key) != expected
    }
    if disagreements:
        raise ValueError(f"Unexpected exhaustive validation state: {disagreements}")
    for key in (
        "expected_candidate_passes",
        "resolved_candidate_passes",
        "finite_survival_passes",
        "independent_cloud_finite_passes",
    ):
        if int(validation[key]) != 107:
            raise ValueError(f"{key} must equal the frozen 107-candidate seal")
    if int(validation["n_cloud_view_layer_pairs_audited"]) != 560:
        raise ValueError("the complete 560-pair diagnostic is required")
    if int(validation["n_pairs_with_cloud_pixels"]) <= 0:
        raise ValueError("the dependency audit must include cloud-bearing pairs")
    if int(validation["n_pairwise_cloud_pixels_with_valid_view"]) != 0:
        raise ValueError("the recorded stop assumes zero cloudy/valid-view overlap")
    diagnostic = pd.read_csv(QUALITY / "cloud_view_mask_dependency_diagnostic.csv")
    if len(diagnostic) != 560:
        raise ValueError("cloud/view diagnostic row count changed")
    return validation, diagnostic


def main() -> int:
    validation, diagnostic = _load_and_validate()
    validation_path = QUALITY / "cloud_exhaustive_validation.json"
    diagnostic_path = QUALITY / "cloud_view_mask_dependency_diagnostic.csv"
    run_record_path = QUALITY / "run_record.json"
    report = {
        "schema_version": 1,
        "run_id": "R0003",
        "decision_ids": ["D0033", "D0034"],
        "task1_gate": EXPECTED_STATUS,
        "exhaustive_asset_census_complete": True,
        "scientific_gate_eligible": False,
        "candidate_seal_geometry_only": False,
        "candidate_passes": 107,
        "cloud_view_pairs_audited": 560,
        "cloud_bearing_pairs": int(validation["n_pairs_with_cloud_pixels"]),
        "cloud_pixels_independent_of_view": int(
            validation["n_pairwise_cloud_pixels_independent_of_view"]
        ),
        "cloud_pixels_with_valid_view": int(
            validation["n_pairwise_cloud_pixels_with_valid_view"]
        ),
        "provisional_expected_pass_equivalents": float(
            validation["sum_cloud_survival_fraction_of_domain"]
        ),
        "provisional_planning_floor": int(validation["conservative_planning_floor"]),
        "planning_floor_status": "PROVISIONAL_NOT_GATE_ELIGIBLE",
        "hrrr_request_manifest": "not_created_due_to_scientific_stop",
        "hrrr_exact_acquisition_fetch": "not_started_due_to_scientific_stop",
        "definitive_step2": "not_run_due_to_invalid_candidate_seal",
        "definitive_step3": "not_run_due_to_uncertified_count",
        "task2": "not_started_because_task1_did_not_pass",
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
        "lst_or_thermal_layers_opened": 0,
        "cloud_validation_sha256": _sha256(validation_path),
        "cloud_view_diagnostic_sha256": _sha256(diagnostic_path),
        "quality_run_record_sha256": _sha256(run_record_path),
        "diagnostic_rows": int(len(diagnostic)),
    }
    _atomic_text(
        OUTPUT / "task1_remediation_gate.json",
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )

    memo = f"""# Task 1 remediation gate

**Gate: STOP — the frozen view-coverage screen is cloud-conditioned.**

The user-approved D0033 census successfully resolved all **107/107** candidate
passes and all **560** selected cloud/view scene-tile pairs without opening an
LST layer. Its apparent expected total is **{report['provisional_expected_pass_equivalents']:.4f}**
pass-equivalents (floor **{report['provisional_planning_floor']}**), but that value
is provisional and cannot enter Step 3.

## Decisive QA result

The official LP DAAC tiled-product guide states that float32 layers contain NaN
where retrieval is unavailable and that the cloud/water masks explain those
missing values. The complete diagnostic found **{report['cloud_bearing_pairs']}**
cloud-bearing layer pairs and **{report['cloud_pixels_independent_of_view']:,}**
cloudy pixels; exactly **0** of those pixels had a valid `view_zenith` value.
Consequently, the earlier 95% valid-view coverage filter used cloud-conditioned
retrieval availability rather than cloud-independent physical view coverage.
The 107 rows therefore cannot be certified as a pre-cloud candidate census.

Official source: [ECOSTRESS Collection 2 Grid/Tile User Guide](https://lpdaac.usgs.gov/documents/1566/ECOL2-4_Grid_Tile_User_Guide_V2.pdf).

## Consequence

No HRRR request manifest or exact-acquisition weather cache was created, the
definitive Step 2/3 runs were not launched, and Task 2 did not start. The held-out
city remains unselected, the entire 2026 season remains unopened, and no thermal
outcome has been inspected. Reopening requires a new pre-outcome decision and a
cloud-independent view-geometry source, preferably L1B GEO, followed by a complete
rescreen of all metadata candidates.
"""
    _atomic_text(OUTPUT / "M2.2_cloud_conditioned_view_stop.md", memo)

    task1 = f"""# Task 1 feasibility result

**Overall status: STOP / `STOP_CLOUD_CONDITIONED_VIEW_GATE`.**

- Step 1 remains complete and canonical: `cross_city_separation_only`.
- The D0033 exhaustive cloud asset census is mechanically complete at 107/107,
  but D0034 makes its apparent floor of {report['provisional_planning_floor']}
  gate-ineligible because valid `view_zenith` coverage was cloud-conditioned.
- HRRR and definitive Step 3 were correctly blocked before execution.
- Task 2 did not start. The holdout remains `UNSELECTED`, 2026 remains unopened,
  and no ECOSTRESS temperature layer was opened.

See `step2_remediation/M2.2_cloud_conditioned_view_stop.md` and the exhaustive
cloud/view diagnostic for the evidence. A new user/supervisor-approved,
cloud-independent geometry rule is required before Task 1 can be reopened.
"""
    _atomic_text(TASK1_GATE, task1)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
