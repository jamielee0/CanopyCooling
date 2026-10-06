#!/usr/bin/env python3
"""Recover nonthermal five-field geometry for the frozen v6.2 D1a pass set.

This runner intentionally reuses the checksum-bound D0069 range-read engine,
but changes only its candidate population and output roots.  It opens latitude,
longitude, view zenith, view azimuth, and solar azimuth from ECO_L1B_GEO.002;
it never opens an LST, temperature, or other thermal-response layer.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

import run_v2_hitl_gate3_second_augmentation as engine


ROOT = Path(__file__).resolve().parents[1]
PASS_DETAIL = ROOT / (
    "docs/v2/hitl/G3_SAMPLING_DESIGN/"
    "angle_threshold_pass_detail_existing_five.csv"
)
OUTPUT_ROOT = ROOT / "data/raw/v2/v6_2/d1a_geometry_recovery"
SUMMARY = ROOT / "data/processed/v2/v6_2/d1a_geometry_recovery/pass_summary.csv"

DECISION_ID = "V6.2-D1A-GEOMETRY-RECOVERY"
ALGORITHM_VERSION = "v6.2-d1a-five-field-geometry-recovery-v1"


def _strict_true(values: pd.Series) -> pd.Series:
    return values.astype("string").str.casefold().eq("true")


def d1a_population() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail = pd.read_csv(PASS_DETAIL)
    candidates = detail.loc[
        detail["city"].isin(["phoenix", "los_angeles"])
        & pd.to_numeric(detail["threshold_deg"], errors="coerce").eq(25)
        & _strict_true(detail["quality_and_exact_weather_complete"])
    ].copy()
    candidates["orbit"] = pd.to_numeric(candidates["orbit"], errors="raise").astype(int)
    candidates["acquisition_utc"] = pd.to_datetime(
        candidates["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    candidates["window_id"] = "jun_sep"
    candidates["source_population"] = "existing_d0047"
    candidates["archive_status"] = "ACCESSIBLE"
    candidates = candidates[
        [
            "city",
            "window_id",
            "orbit",
            "acquisition_utc",
            "source_population",
            "archive_status",
        ]
    ].drop_duplicates(["city", "orbit"])
    counts = candidates.groupby("city").size().to_dict()
    if counts != {"los_angeles": 48, "phoenix": 44} or len(candidates) != 92:
        raise ValueError(f"Frozen D1a candidate census changed: {counts}")

    links = pd.read_csv(engine.EXISTING_LINKS)
    links["orbit"] = pd.to_numeric(links["orbit"], errors="raise").astype(int)
    links["scene"] = pd.to_numeric(links["scene"], errors="raise").astype(int)
    links = links.merge(
        candidates[["city", "orbit"]],
        on=["city", "orbit"],
        how="inner",
        validate="many_to_one",
    )
    links = links[["city", "orbit", "scene", "scene_acquisition_utc"]].copy()
    if len(links) != 139 or links.duplicated(["orbit", "scene"]).any():
        raise ValueError("Frozen D1a scene-link census changed")
    return candidates.copy(), links, candidates.copy()


def configure_engine() -> None:
    def target_grids(geometries: dict[str, Any]) -> dict[str, dict[str, Any]]:
        views = pd.read_csv(engine.EXISTING_VIEW_MANIFEST)
        denominators = pd.read_csv(engine.EXISTING_DENOMINATORS)
        cities = set(geometries)
        return engine.build_canonical_target_grids(
            views.loc[views["city"].isin(cities)],
            domain_geometries_wgs84=geometries,
            asset_root=engine.ASSET_ROOT,
            denominator_table=denominators.loc[denominators["city"].isin(cities)],
        )

    engine.DECISION_ID = DECISION_ID
    engine.ALGORITHM_VERSION = ALGORITHM_VERSION
    engine.PRIMARY_WINDOWS = {"phoenix": "jun_sep", "los_angeles": "jun_sep"}
    engine.RAW = OUTPUT_ROOT
    engine.PROCESSED = SUMMARY.parent
    engine.PASS_EVIDENCE = OUTPUT_ROOT / "pass_evidence"
    engine.GEOMETRY_RECONSTRUCTION = OUTPUT_ROOT / "reconstruction"
    engine.GEOMETRY_RECONSTRUCTION_PREFLIGHT = OUTPUT_ROOT / "storage_preflight.json"
    engine.PASS_CHECKPOINT = OUTPUT_ROOT / "checkpoint.json"
    engine.GEOMETRY_SUMMARY = SUMMARY
    engine._geometry_population = d1a_population
    engine._target_grids = target_grids
    # The reused engine ordinarily checks D0069's separate new-pass archive
    # before constructing its mixed old/new population.  D1a is sealed to the
    # 92 archive-available D0047 passes above, so that unrelated prerequisite
    # is intentionally replaced by an empty, no-op record.
    engine._require_resolved_new_archive = lambda: pd.DataFrame()


def write_manifest() -> None:
    table = pd.read_csv(SUMMARY)
    complete = _strict_true(table["geometry_azimuth_complete"])
    checkpoint_document = json.loads(
        (OUTPUT_ROOT / "checkpoint.json").read_text(encoding="utf-8")
    )
    checkpoint = checkpoint_document.get("items", checkpoint_document)
    if len(checkpoint) != len(table):
        raise ValueError("D1a recovery checkpoint is not pass-complete")
    evidence_hashes: list[str] = []
    for row in table.itertuples(index=False):
        item_id = f"{row.city}:{int(row.orbit):05d}"
        record = checkpoint.get(item_id, {})
        evidence_path = Path(str(record.get("evidence_path", "")))
        if not (
            record.get("status") == "complete"
            and evidence_path.is_file()
            and re.fullmatch(r"[0-9a-f]{64}", str(record.get("evidence_sha256", "")))
            and engine.sha256_file(evidence_path) == record["evidence_sha256"]
        ):
            raise ValueError(f"D1a recovery evidence does not validate: {item_id}")
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not (
            document.get("status") == "complete"
            and document.get("temperature_or_lst_opened") is False
            and document.get("record_2026_opened") is False
            and str(document.get("binding", {}).get("decision_id")) == DECISION_ID
            and str(document.get("binding", {}).get("city")) == str(row.city)
            and int(document.get("binding", {}).get("orbit", -1)) == int(row.orbit)
            and engine._reconstruction_cache_valid(
                document,
                expected_city=str(row.city),
                expected_window_id="jun_sep",
                expected_orbit=int(row.orbit),
                expected_target_grid_sha256=str(
                    document["binding"]["target_grid_sha256"]
                ),
                expected_n_domain_pixels=int(row.n_domain_pixels),
                expected_path=Path(document["reconstruction_artifact"]["path"]),
            )
        ):
            raise ValueError(f"D1a recovery reconstruction does not validate: {item_id}")
        evidence_hashes.append(f"{item_id}:{record['evidence_sha256']}")
    payload: dict[str, Any] = {
        "decision_id": DECISION_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "source_product": "ECO_L1B_GEO.002",
        "variables_opened": [
            "latitude",
            "longitude",
            "view_zenith",
            "view_azimuth",
            "solar_azimuth",
        ],
        "temperature_or_lst_opened": False,
        "new_v6_2_coefficient_opened": False,
        "candidate_passes": int(len(table)),
        "complete_passes": int(complete.sum()),
        "validated_pass_evidence_records": int(len(evidence_hashes)),
        "pass_evidence_inventory_sha256": engine.sha256_strings(evidence_hashes),
        "status_counts": table["geometry_azimuth_status"].value_counts().sort_index().to_dict(),
        "city_counts": {
            str(city): {
                "candidate": int(len(group)),
                "complete": int(_strict_true(group["geometry_azimuth_complete"]).sum()),
            }
            for city, group in table.groupby("city", sort=True)
        },
    }
    path = SUMMARY.parent / "manifest.json"
    engine._atomic_json(payload, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    configure_engine()
    engine.run_geometry(max(1, args.workers))
    write_manifest()


if __name__ == "__main__":
    main()
