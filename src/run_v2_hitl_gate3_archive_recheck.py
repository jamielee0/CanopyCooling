#!/usr/bin/env python3
"""Run the finite D0067/D0068 nonthermal recheck of 31 historical passes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in os.sys.path:
    os.sys.path.insert(0, str(ROOT / "src"))

from run_v2_step02_l1b_geometry import _earthaccess
from urban_cooling_v2.step02_l1b_identity_audit import canonical_identity_urls


DECISION_IDS = ["D0067", "D0068"]
COLLECTION_CONCEPT_ID = "C2076087338-LPCLOUD"
CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
SOURCE_SCENES = ROOT / "data/processed/v2/task1/step2_l1b_identity_audit_D0038/scene_identity_resolution.csv"
SOURCE_PASSES = ROOT / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/archive_missing_31_audit.csv"
AVAILABLE_MANIFEST = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/l1b_geo_scene_manifest.csv"
OUTPUT = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _bounded_range_status(session: Any, url: str) -> tuple[int | None, str, str]:
    response = None
    try:
        response = session.get(
            url,
            headers={"Range": "bytes=0-7"},
            stream=True,
            allow_redirects=True,
            timeout=(30, 120),
        )
        status = int(response.status_code)
        prefix = next(response.iter_content(chunk_size=8), b"")[:8]
        return status, hashlib.sha256(prefix).hexdigest() if prefix else "", ""
    except Exception as exc:  # finite result records the class, never retries here
        return None, "", type(exc).__name__
    finally:
        if response is not None:
            response.close()


def _control(session: Any) -> dict[str, Any]:
    manifest = pd.read_csv(AVAILABLE_MANIFEST)
    row = manifest.loc[manifest["status"].astype(str).eq("available")].iloc[0]
    hdf_status, hdf_hash, hdf_error = _bounded_range_status(session, str(row["hdf_url"]))
    dmrpp_status, dmrpp_hash, dmrpp_error = _bounded_range_status(session, str(row["dmrpp_url"]))
    passed = hdf_status in {200, 206} and dmrpp_status in {200, 206}
    return {
        "granule_id": str(row["granule_id"]),
        "hdf_status": hdf_status,
        "hdf_prefix_sha256": hdf_hash,
        "hdf_error_type": hdf_error,
        "dmrpp_status": dmrpp_status,
        "dmrpp_prefix_sha256": dmrpp_hash,
        "dmrpp_error_type": dmrpp_error,
        "passed": passed,
    }


def _assemble_outputs(
    scene_result: pd.DataFrame,
    passes: pd.DataFrame,
    control: dict[str, Any],
) -> dict[str, Any]:
    scene_path = OUTPUT / "archive_scene_bounded_recheck.csv"
    scene_lookup = scene_result.set_index(["orbit", "scene"])
    pass_rows: list[dict[str, Any]] = []
    for source in passes.to_dict("records"):
        keys = [
            tuple(int(part) for part in value.split("_"))
            for value in str(source["unavailable_l1b_scene_keys"]).split(";")
            if value
        ]
        statuses = [str(scene_lookup.loc[key, "scene_recheck_classification"]) for key in keys]
        if "UNRESOLVED_ERROR" in statuses:
            classification = "UNRESOLVED_ERROR"
        elif "RECOVERY_IDENTITY_ACCESSIBLE_GEOMETRY_PENDING" in statuses:
            classification = "RECOVERY_PENDING_GEOMETRY"
        else:
            classification = "RESOLVED_UNAVAILABLE"
        pass_rows.append(
            {
                **source,
                "bounded_scene_statuses": "|".join(statuses),
                "pass_recheck_classification": classification,
                "lower_bound_geometry_qualified_contribution": 0,
                "upper_bound_geometry_qualified_contribution": int(
                    classification == "RESOLVED_UNAVAILABLE"
                ),
            }
        )
    pass_result = pd.DataFrame(pass_rows)
    pass_path = OUTPUT / "archive_pass_bounded_recheck_and_bounds.csv"
    pass_result.to_csv(pass_path, index=False)

    summary = {
        "decision_ids": DECISION_IDS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "collection": "ECO_L1B_GEO.002",
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "version_003_l1b_query_performed": False,
        "source_correction": "D0068: no official ECO_L1B_GEO.003 collection",
        "scene_count": len(scene_result),
        "pass_count": len(pass_result),
        "scene_classification_counts": scene_result["scene_recheck_classification"].value_counts().to_dict(),
        "pass_classification_counts": pass_result["pass_recheck_classification"].value_counts().to_dict(),
        "available_object_control": control,
        "finite_budget_observed": bool(
            scene_result["query_count_this_run"].eq(1).all()
            and scene_result["hdf_access_attempts_this_run"].eq(1).all()
            and scene_result["dmrpp_access_attempts_this_run"].eq(1).all()
        ),
        "unresolved_error_count": int(
            pass_result["pass_recheck_classification"].eq("UNRESOLVED_ERROR").sum()
        ),
        "source_hashes": {
            str(SOURCE_SCENES.relative_to(ROOT)): _sha256_file(SOURCE_SCENES),
            str(SOURCE_PASSES.relative_to(ROOT)): _sha256_file(SOURCE_PASSES),
            str(AVAILABLE_MANIFEST.relative_to(ROOT)): _sha256_file(AVAILABLE_MANIFEST),
        },
        "artifact_hashes": {
            str(scene_path.relative_to(ROOT)): _sha256_file(scene_path),
            str(pass_path.relative_to(ROOT)): _sha256_file(pass_path),
        },
        "temperature_or_lst_opened": False,
        "record_2026_queried": False,
    }
    summary_path = OUTPUT / "archive_bounded_recheck_summary.json"
    _atomic_json(summary, summary_path)
    return summary


def run() -> dict[str, Any]:
    scenes = pd.read_csv(SOURCE_SCENES)
    passes = pd.read_csv(SOURCE_PASSES)
    if len(scenes) != 41 or len(passes) != 31:
        raise ValueError("The frozen inaccessible scene/pass census changed")
    acquisitions = pd.to_datetime(scenes["scene_acquisition_utc"], utc=True, errors="raise")
    if acquisitions.dt.year.min() < 2018 or acquisitions.dt.year.max() > 2025:
        raise ValueError("Archive recheck escaped 2018–2025")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    scene_path = OUTPUT / "archive_scene_bounded_recheck.csv"
    if scene_path.exists():
        prior = pd.read_csv(scene_path)
        if (
            len(prior) != 41
            or prior.duplicated(["orbit", "scene"]).any()
            or not prior["query_count_this_run"].eq(1).all()
            or not prior["hdf_access_attempts_this_run"].eq(1).all()
            or not prior["dmrpp_access_attempts_this_run"].eq(1).all()
            or prior["record_2026_queried"].astype(str).str.casefold().ne("false").any()
        ):
            raise ValueError("Existing one-time scene recheck is incomplete or unsafe")
        return _assemble_outputs(
            prior,
            passes,
            {
                "passed": True,
                "status": "REUSED_PASSING_CONTROL_FROM_ONE_TIME_SCENE_RECHECK",
                "target_queries_repeated": False,
            },
        )

    earthaccess, _ = _earthaccess()
    session = earthaccess.get_requests_https_session()
    control = _control(session)
    if not control["passed"]:
        raise RuntimeError("Bounded available-object control failed; target results would be ambiguous")

    rows: list[dict[str, Any]] = []
    for source, acquisition in zip(scenes.to_dict("records"), acquisitions):
        granule_id = str(source["geo_granule_id"])
        day_start = acquisition.floor("D")
        day_end = day_start + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
        params = {
            "collection_concept_id": COLLECTION_CONCEPT_ID,
            "producer_granule_id": granule_id,
            "temporal": f"{day_start.strftime('%Y-%m-%dT%H:%M:%SZ')},{day_end.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z",
            "page_size": 10,
        }
        query_error = ""
        query_status: int | None = None
        response_sha256 = ""
        hit_ids: list[str] = []
        response = None
        try:
            response = session.get(
                CMR_URL,
                params=params,
                headers={"Accept": "application/vnd.nasa.cmr.umm_results+json"},
                timeout=(30, 120),
            )
            query_status = int(response.status_code)
            response.raise_for_status()
            document = response.json()
            response_sha256 = hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            items = document.get("items", [])
            hit_ids = [str(item.get("umm", {}).get("GranuleUR", "")) for item in items]
            if any(value != granule_id for value in hit_ids) or len(hit_ids) > 1:
                raise ValueError("Ambiguous or nonexact CMR result")
        except Exception as exc:
            query_error = type(exc).__name__
        finally:
            if response is not None:
                response.close()

        urls = canonical_identity_urls(granule_id)
        hdf_status, hdf_prefix_hash, hdf_error = _bounded_range_status(session, urls["hdf_url"])
        dmrpp_status, dmrpp_prefix_hash, dmrpp_error = _bounded_range_status(session, urls["dmrpp_url"])
        accessible = hdf_status in {200, 206} and dmrpp_status in {200, 206}
        if query_error:
            classification = "UNRESOLVED_ERROR"
        elif accessible:
            classification = "RECOVERY_IDENTITY_ACCESSIBLE_GEOMETRY_PENDING"
        else:
            classification = "RESOLVED_UNAVAILABLE"
        rows.append(
            {
                "orbit": int(source["orbit"]),
                "scene": int(source["scene"]),
                "scene_acquisition_utc": acquisition.isoformat(),
                "cities": str(source["cities"]),
                "geo_granule_id": granule_id,
                "query_temporal_start": params["temporal"].split(",")[0],
                "query_temporal_end": params["temporal"].split(",")[1],
                "cmr_http_status": query_status,
                "cmr_exact_hits": len(hit_ids),
                "cmr_response_sha256": response_sha256,
                "cmr_error_type": query_error,
                "hdf_range_status": hdf_status,
                "hdf_prefix_sha256": hdf_prefix_hash,
                "hdf_error_type": hdf_error,
                "dmrpp_range_status": dmrpp_status,
                "dmrpp_prefix_sha256": dmrpp_prefix_hash,
                "dmrpp_error_type": dmrpp_error,
                "scene_recheck_classification": classification,
                "query_count_this_run": 1,
                "hdf_access_attempts_this_run": 1,
                "dmrpp_access_attempts_this_run": 1,
                "temperature_or_lst_opened": False,
                "record_2026_queried": False,
            }
        )

    scene_result = pd.DataFrame(rows).sort_values(["orbit", "scene"])
    scene_result.to_csv(scene_path, index=False)
    return _assemble_outputs(scene_result, passes, control)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
