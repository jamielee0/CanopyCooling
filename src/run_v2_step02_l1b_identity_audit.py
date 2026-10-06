#!/usr/bin/env python3
"""Run the D0038 metadata-only audit of 41 orphan L1B GEO identities."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in os.sys.path:
    os.sys.path.insert(0, str(ROOT / "src"))

from run_v2_step02_l1b_geometry import _earthaccess, _exact_scene_query
from urban_cooling_v2.step02_l1b_identity_audit import (
    COLLECTION_CONCEPT_ID,
    DECISION_ID,
    EXPECTED_MISSING_SCENES,
    EXPECTED_SELECTED_SIDECARS,
    canonical_identity_urls,
    classify_identity_resolution,
    extract_geo_pointer,
    sha256_file,
    sha256_text,
    validate_exact_cmr_response,
    validate_opendap_dmr,
)


SCENE_MANIFEST = (
    ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0035/l1b_geo_scene_manifest.csv"
)
CMR_CACHE = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0035/cmr/by_scene"
VIEW_MANIFEST = ROOT / "data/raw/v2/ecostress/view_candidate_manifest_latest.csv"
ENRICHMENT_MANIFEST = ROOT / "data/raw/v2/ecostress/enrichment_manifest.csv"
ASSET_ROOT = ROOT / "data/raw/v2/ecostress/enrichment_assets"
ASSET_CHECKPOINT = ASSET_ROOT / "checkpoint.json"
OUTPUT_DIR = ROOT / "data/processed/v2/task1/step2_l1b_identity_audit_D0038"
SIDECAR_EVIDENCE = OUTPUT_DIR / "l2t_inputpointer_evidence.csv"
SCENE_RESOLUTION = OUTPUT_DIR / "scene_identity_resolution.csv"
VALIDATION = OUTPUT_DIR / "identity_validation.json"
RUN_RECORD = OUTPUT_DIR / "run_record.json"
SUPPORT_PACKET = OUTPUT_DIR / "LPDAAC_support_packet.md"
CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
TASK1_OUTPUT_ROOT = ROOT / "data/processed/v2/task1"
DECISION_ID_PATTERN = re.compile(r"D[0-9]{4}")
RUN_ID_PATTERN = re.compile(r"R[0-9]{4}(?:_[A-Za-z0-9]+)?")


def _atomic_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_csv(value: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    value.to_csv(temporary, index=False)
    temporary.replace(path)


def _atomic_text(value: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _checkpoint_items() -> dict[str, dict[str, Any]]:
    document = json.loads(ASSET_CHECKPOINT.read_text(encoding="utf-8"))
    items = document.get("items")
    if document.get("schema_version") != 1 or not isinstance(items, dict):
        raise ValueError("Enrichment asset checkpoint is malformed")
    return {str(key): dict(value) for key, value in items.items()}


def _relative_local_path(value: Any) -> Path:
    path = Path(str(value))
    absolute = path if path.is_absolute() else ROOT / path
    resolved = absolute.resolve()
    allowed = (ASSET_ROOT / "l2t_json").resolve()
    if resolved.parent != allowed:
        raise ValueError("D0038 sidecar path escapes the verified L2T JSON directory")
    return resolved


def _load_frozen_missing() -> pd.DataFrame:
    manifest = pd.read_csv(SCENE_MANIFEST)
    if len(manifest) != 1_370 or manifest.duplicated(["orbit", "scene"]).any():
        raise ValueError("D0038 source scene manifest is not the sealed 1,370-row census")
    missing = manifest.loc[~manifest["status"].astype(str).eq("available")].copy()
    if (
        len(missing) != EXPECTED_MISSING_SCENES
        or not missing["status"].astype(str).eq("missing").all()
        or missing["cmr_query_error_type"].fillna("").astype(str).str.len().gt(0).any()
        or not missing["decision_id"].astype(str).eq("D0035").all()
        or not missing["lst_opened"].astype(str).str.casefold().eq("false").all()
        or not missing["record_2026_opened"].astype(str).str.casefold().eq("false").all()
    ):
        raise ValueError("D0038 source missing-scene seal changed")
    return missing.sort_values(["orbit", "scene"], kind="stable").reset_index(drop=True)


def _recover_sidecar_evidence(
    missing: pd.DataFrame, *, decision_id: str = DECISION_ID
) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = missing[["orbit", "scene"]].astype(int)
    views = pd.read_csv(VIEW_MANIFEST).merge(
        keys, on=["orbit", "scene"], how="inner", validate="many_to_one"
    )
    if (
        len(views) != EXPECTED_SELECTED_SIDECARS
        or views["granule_id"].astype(str).duplicated().any()
        or not views["status"].astype(str).eq("available").all()
        or not views["asset_type"].astype(str).eq("view_zenith_cog").all()
    ):
        raise ValueError("D0038 selected L2T sidecar census changed")
    enrichment = pd.read_csv(ENRICHMENT_MANIFEST)
    json_rows = enrichment.loc[
        enrichment["asset_type"].astype(str).eq("l2t_json")
    ].merge(
        views[["city", "granule_id"]],
        on=["city", "granule_id"],
        how="inner",
        validate="one_to_one",
    )
    if (
        len(json_rows) != EXPECTED_SELECTED_SIDECARS
        or not json_rows["status"].astype(str).eq("available").all()
        or not json_rows["source_url"]
        .astype(str)
        .str.startswith("https://data.lpdaac.earthdatacloud.nasa.gov/")
        .all()
    ):
        raise ValueError("D0038 L2T JSON manifest evidence changed")
    checkpoint = _checkpoint_items()
    rows: list[dict[str, Any]] = []
    for record in json_rows.sort_values(["orbit", "scene", "city", "tile"]).to_dict(
        "records"
    ):
        item_id = str(record["item_id"])
        item = checkpoint.get(item_id)
        if not item or item.get("status") != "complete":
            raise ValueError(f"Missing verified L2T JSON checkpoint: {item_id}")
        path = _relative_local_path(item.get("local_path"))
        expected_name = str(record["granule_id"]) + ".json"
        if path.name != expected_name or not path.is_file():
            raise ValueError(f"L2T JSON path mismatch: {item_id}")
        size = path.stat().st_size
        digest = sha256_file(path)
        if int(item.get("size_bytes", -1)) != size or item.get("sha256") != digest:
            raise ValueError(f"L2T JSON checkpoint digest mismatch: {item_id}")
        document = json.loads(path.read_text(encoding="utf-8"))
        standard = document.get("StandardMetadata")
        if not isinstance(standard, Mapping):
            raise ValueError(f"L2T JSON lacks StandardMetadata: {item_id}")
        if str(standard.get("LocalGranuleID", "")) != str(record["granule_id"]) + ".zip":
            raise ValueError(f"L2T JSON LocalGranuleID mismatch: {item_id}")
        pointer = extract_geo_pointer(standard.get("InputPointer"))
        acquisition = pd.Timestamp(record["acquisition_utc"])
        expected_stamp = acquisition.strftime("%Y%m%dT%H%M%S")
        if (
            int(pointer["orbit"]) != int(record["orbit"])
            or int(pointer["scene"]) != int(record["scene"])
            or pointer["stamp"] != expected_stamp
        ):
            raise ValueError(f"L2T InputPointer identity mismatch: {item_id}")
        rows.append(
            {
                "orbit": int(record["orbit"]),
                "scene": int(record["scene"]),
                "city": str(record["city"]),
                "tile": str(record["tile"]),
                "l2t_granule_id": str(record["granule_id"]),
                "l2t_json_item_id": item_id,
                "l2t_json_relative_path": str(path.relative_to(ROOT)),
                "l2t_json_size_bytes": size,
                "l2t_json_sha256": digest,
                "l2t_json_source_url": str(record["source_url"]),
                **pointer,
                "evidence_status": "verified_selected_l2t_inputpointer",
                "geometry_values_opened": False,
                "decision_id": decision_id,
            }
        )
    evidence = pd.DataFrame(rows)
    scene_rows: list[dict[str, Any]] = []
    missing_lookup = missing.set_index(["orbit", "scene"])
    for (orbit, scene), group in evidence.groupby(["orbit", "scene"], sort=True):
        identities = sorted(group["geo_granule_id"].astype(str).unique())
        if len(identities) != 1:
            raise ValueError(f"L2T tiles disagree on GEO identity for {orbit}/{scene}")
        cmr_cache = CMR_CACHE / f"{int(orbit):05d}_{int(scene):03d}.json"
        cache_document = json.loads(cmr_cache.read_text(encoding="utf-8"))
        if (
            cache_document.get("query") != _exact_scene_query(int(orbit), int(scene))
            or cache_document.get("results") != []
        ):
            raise ValueError(f"D0038 fallback key is not an exact CMR-empty cache: {orbit}/{scene}")
        row = missing_lookup.loc[(int(orbit), int(scene))]
        granule_id = identities[0]
        scene_rows.append(
            {
                "orbit": int(orbit),
                "scene": int(scene),
                "scene_acquisition_utc": str(row["scene_acquisition_utc"]),
                "cities": str(row["cities"]),
                "geo_granule_id": granule_id,
                "geo_filename": granule_id + ".h5",
                "selected_l2t_sidecar_count": int(len(group)),
                "selected_l2t_sidecar_set_sha256": sha256_text(
                    "\n".join(sorted(group["l2t_json_sha256"].astype(str)))
                ),
                "cmr_empty_cache_relative_path": str(cmr_cache.relative_to(ROOT)),
                "cmr_empty_cache_sha256": sha256_file(cmr_cache),
                **canonical_identity_urls(granule_id),
                "geometry_values_opened": False,
                "decision_id": decision_id,
            }
        )
    scenes = pd.DataFrame(scene_rows)
    if len(evidence) != EXPECTED_SELECTED_SIDECARS or len(scenes) != EXPECTED_MISSING_SCENES:
        raise ValueError("D0038 evidence cardinality changed")
    return evidence, scenes


def _probe_scenes(
    scenes: pd.DataFrame,
    *,
    session_factory: Any,
    max_workers: int,
    decision_id: str = DECISION_ID,
) -> pd.DataFrame:
    local = threading.local()

    def session() -> Any:
        if not hasattr(local, "value"):
            local.value = session_factory()
        return local.value

    def worker(record: Mapping[str, Any]) -> dict[str, Any]:
        output = dict(record)
        client = session()
        granule = str(record["geo_granule_id"])
        cmr_hits = 0
        cmr_hash = ""
        cmr_error = ""
        try:
            response = client.get(
                CMR_URL,
                params={
                    "collection_concept_id": COLLECTION_CONCEPT_ID,
                    "producer_granule_id": granule,
                    "page_size": 2000,
                },
                headers={"Accept": "application/vnd.nasa.cmr.umm_results+json"},
                timeout=(30, 120),
            )
            if int(response.status_code) != 200:
                raise RuntimeError(f"CMR_HTTP_{response.status_code}")
            cmr_hits, cmr_hash = validate_exact_cmr_response(response.json(), granule)
            response.close()
        except Exception as exc:
            cmr_error = type(exc).__name__

        endpoint_values: dict[str, Any] = {}
        for label in ("hdf_url", "dmrpp_url"):
            response = None
            try:
                response = client.head(
                    str(record[label]), allow_redirects=True, timeout=(30, 120)
                )
                endpoint_values[label.replace("_url", "_http_status")] = int(
                    response.status_code
                )
                endpoint_values[label.replace("_url", "_content_length")] = str(
                    response.headers.get("Content-Length", "")
                )
                endpoint_values[label.replace("_url", "_etag")] = str(
                    response.headers.get("ETag", "")
                )
                endpoint_values[label.replace("_url", "_version_id")] = str(
                    response.headers.get("x-amz-version-id", "")
                )
                endpoint_values[label.replace("_url", "_error_type")] = ""
            except Exception as exc:
                endpoint_values[label.replace("_url", "_http_status")] = None
                endpoint_values[label.replace("_url", "_content_length")] = ""
                endpoint_values[label.replace("_url", "_etag")] = ""
                endpoint_values[label.replace("_url", "_version_id")] = ""
                endpoint_values[label.replace("_url", "_error_type")] = type(exc).__name__
            finally:
                if response is not None:
                    response.close()

        opendap_status: int | None = None
        opendap_valid = False
        opendap_hash = ""
        opendap_error = ""
        response = None
        try:
            response = client.get(
                str(record["opendap_dmr_url"]), timeout=(30, 120), allow_redirects=True
            )
            opendap_status = int(response.status_code)
            if opendap_status == 200:
                opendap_hash = validate_opendap_dmr(bytes(response.content), granule)
                opendap_valid = True
        except Exception as exc:
            opendap_error = type(exc).__name__
        finally:
            if response is not None:
                response.close()

        status = classify_identity_resolution(
            cmr_exact_hits=cmr_hits,
            hdf_status=endpoint_values.get("hdf_http_status"),
            dmrpp_status=endpoint_values.get("dmrpp_http_status"),
            opendap_status=opendap_status,
            opendap_metadata_valid=opendap_valid,
        )
        output.update(
            {
                "cmr_exact_producer_id_hits": cmr_hits,
                "cmr_response_sha256": cmr_hash,
                "cmr_error_type": cmr_error,
                **endpoint_values,
                "opendap_dmr_http_status": opendap_status,
                "opendap_dmr_metadata_valid": opendap_valid,
                "opendap_dmr_sha256": opendap_hash,
                "opendap_dmr_error_type": opendap_error,
                "identity_resolution_status": status,
                "retrieval_utc": datetime.now(timezone.utc).isoformat(),
                "geometry_values_opened": False,
                "decision_id": decision_id,
            }
        )
        return output

    output: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(worker, row): (int(row["orbit"]), int(row["scene"]))
            for row in scenes.to_dict("records")
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                output.append(future.result())
            except Exception as exc:
                raise RuntimeError(f"D0038 worker failed for {key}: {type(exc).__name__}") from exc
    return pd.DataFrame(output).sort_values(["orbit", "scene"], kind="stable").reset_index(
        drop=True
    )


def _validation(
    resolution: pd.DataFrame,
    evidence: pd.DataFrame,
    *,
    decision_id: str = DECISION_ID,
    source_gate_decision_id: str = "D0037",
) -> dict[str, Any]:
    verified = resolution["identity_resolution_status"].astype(str).eq(
        "verified_exact_cmr"
    )
    complete = bool(len(resolution) == EXPECTED_MISSING_SCENES and verified.all())
    return {
        "decision_id": decision_id,
        "source_gate_decision_id": source_gate_decision_id,
        "expected_missing_scene_count": EXPECTED_MISSING_SCENES,
        "selected_l2t_sidecar_count": int(len(evidence)),
        "exact_cmr_verified_count": int(verified.sum()),
        "exact_object_uncataloged_count": int(
            resolution["identity_resolution_status"]
            .astype(str)
            .eq("verified_exact_object_uncataloged")
            .sum()
        ),
        "unresolved_missing_count": int(
            resolution["identity_resolution_status"]
            .astype(str)
            .eq("unresolved_missing")
            .sum()
        ),
        "hdf_http_200_count": int(
            pd.to_numeric(resolution["hdf_http_status"], errors="coerce").eq(200).sum()
        ),
        "dmrpp_http_200_count": int(
            pd.to_numeric(resolution["dmrpp_http_status"], errors="coerce").eq(200).sum()
        ),
        "opendap_dmr_http_200_count": int(
            pd.to_numeric(resolution["opendap_dmr_http_status"], errors="coerce")
            .eq(200)
            .sum()
        ),
        "identity_complete": complete,
        "gate_status": (
            f"PASS_{decision_id}_EXACT_IDENTITIES"
            if complete
            else f"STOP_{decision_id}_INCOMPLETE_IDENTITY"
        ),
        "geometry_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "downstream_authorized": complete,
    }


def _support_packet(
    resolution: pd.DataFrame,
    validation: Mapping[str, Any],
    *,
    decision_id: str = DECISION_ID,
) -> str:
    lines = [
        f"# LP DAAC support packet — {decision_id} orphan L1B GEO identities",
        "",
        "This packet records exact `ECO_L1B_GEO.002` identities named by checksum-verified ",
        "selected `ECO_L2T_LSTE.002` JSON `InputPointer` metadata. No geometry arrays, LST, ",
        "thermal outcome, 2026 observation, or holdout outcome were opened.",
        "",
        f"- Collection concept: `{COLLECTION_CONCEPT_ID}`",
        f"- Exact missing scenes: {len(resolution)}",
        f"- Gate: `{validation['gate_status']}`",
        f"- Exact CMR verified: {validation['exact_cmr_verified_count']}",
        f"- Protected HDF HTTP 200: {validation['hdf_http_200_count']}",
        f"- DMR++ HTTP 200: {validation['dmrpp_http_200_count']}",
        f"- OPeNDAP DMR HTTP 200: {validation['opendap_dmr_http_200_count']}",
        "",
        "## Exact scene list",
        "",
        "| Orbit/scene | Exact InputPointer GEO filename | CMR hits | HDF | DMR++ | OPeNDAP DMR |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in resolution.to_dict("records"):
        lines.append(
            f"| {int(row['orbit']):05d}/{int(row['scene']):03d} | "
            f"`{row['geo_filename']}` | {int(row['cmr_exact_producer_id_hits'])} | "
            f"{row.get('hdf_http_status', '')} | {row.get('dmrpp_http_status', '')} | "
            f"{row.get('opendap_dmr_http_status', '')} |"
        )
    lines.extend(
        [
            "",
            "## Requested action",
            "",
            "Please confirm whether these orphan `ECO_L1B_GEO.002` granules can be restored or "
            "re-indexed. Their downstream L2T products explicitly name the exact GEO inputs, but "
            "the current exact CMR searches and protected-object metadata checks do not resolve them.",
            "",
        ]
    )
    return "\n".join(lines)


def _validated_output_dir(value: Path) -> Path:
    resolved = value if value.is_absolute() else ROOT / value
    resolved = resolved.resolve()
    task1_root = TASK1_OUTPUT_ROOT.resolve()
    if resolved == task1_root or task1_root not in resolved.parents:
        raise ValueError("Identity-audit output must be a child of the v2 Task 1 output root")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--decision-id", default=DECISION_ID)
    parser.add_argument("--source-gate-decision-id", default="D0037")
    parser.add_argument("--run-id", default="R0005_D0038")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly permit replacement of an existing audit output set.",
    )
    args = parser.parse_args()
    if not 1 <= args.max_workers <= 8:
        raise ValueError("D0038 max-workers must be between 1 and 8")
    if not DECISION_ID_PATTERN.fullmatch(str(args.decision_id)):
        raise ValueError("decision-id must have form D0000")
    if not DECISION_ID_PATTERN.fullmatch(str(args.source_gate_decision_id)):
        raise ValueError("source-gate-decision-id must have form D0000")
    if not RUN_ID_PATTERN.fullmatch(str(args.run_id)):
        raise ValueError("run-id must have form R0000 or R0000_LABEL")
    if args.decision_id != DECISION_ID and args.run_id == "R0005_D0038":
        raise ValueError("A refresh decision requires an explicit new run-id")
    output_dir = _validated_output_dir(args.output_dir)
    sidecar_evidence = output_dir / "l2t_inputpointer_evidence.csv"
    scene_resolution = output_dir / "scene_identity_resolution.csv"
    validation_path = output_dir / "identity_validation.json"
    run_record_path = output_dir / "run_record.json"
    support_packet = output_dir / "LPDAAC_support_packet.md"
    artifacts = [sidecar_evidence, scene_resolution, validation_path, support_packet]
    if not args.overwrite and any(path.exists() for path in [*artifacts, run_record_path]):
        raise FileExistsError(
            "Identity-audit output already exists; use a new decision/output path or --overwrite"
        )
    missing = _load_frozen_missing()
    evidence, scenes = _recover_sidecar_evidence(
        missing, decision_id=args.decision_id
    )
    _atomic_csv(evidence, sidecar_evidence)
    earthaccess, _ = _earthaccess()
    resolution = _probe_scenes(
        scenes,
        session_factory=earthaccess.get_requests_https_session,
        max_workers=args.max_workers,
        decision_id=args.decision_id,
    )
    validation = _validation(
        resolution,
        evidence,
        decision_id=args.decision_id,
        source_gate_decision_id=args.source_gate_decision_id,
    )
    _atomic_csv(resolution, scene_resolution)
    _atomic_json(validation, validation_path)
    _atomic_text(
        _support_packet(resolution, validation, decision_id=args.decision_id),
        support_packet,
    )
    run_record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": args.decision_id,
        "profile": "metadata-only exact CMR and official endpoint audit; no array values",
        "gate_status": validation["gate_status"],
        "artifact_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path) for path in artifacts
        },
        "validation": validation,
        "geometry_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    _atomic_json(run_record, run_record_path)
    print(
        f"{args.decision_id} identity audit: {validation['exact_cmr_verified_count']}/"
        f"{validation['expected_missing_scene_count']} exact CMR verified; "
        f"gate {validation['gate_status']}",
        flush=True,
    )
    return 0 if validation["identity_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
