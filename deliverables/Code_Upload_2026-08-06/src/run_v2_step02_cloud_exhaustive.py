#!/usr/bin/env python3
"""Build and run the D0033 exhaustive Step-2 ECOSTRESS cloud audit.

The runner is deliberately separate from canonical run R0002.  It derives a
cloud-only manifest from frozen cached CMR records, optionally downloads only
those cloud COGs, and writes all remediation results to the dedicated
``step2_quality_screening_exhaustive`` directory.  No LST asset is addressable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from urban_cooling_v2.config import load_config
from urban_cooling_v2.domains import load_domain_features
from urban_cooling_v2.step02_cloud_exhaustive import (
    DECISION_ID,
    EXPECTED_CANDIDATE_PASSES,
    build_exhaustive_cloud_manifest,
    build_exhaustive_validation,
    load_cached_l2t_results,
    run_cloud_view_dependency_audit,
    run_exhaustive_cloud_audit,
)
from urban_cooling_v2.step02_enrich import (
    load_checkpoint,
    pending_item_ids,
    write_checkpoint,
)
from urban_cooling_v2.step02_enrich_fetch import (
    CLOUD_COG,
    download_target_manifest_concurrent,
)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/v2/ecostress"
ASSETS = RAW / "enrichment_assets"
PROCESSED = ROOT / "data/processed/v2/task1"

DEFAULT_SCREENED = (
    PROCESSED / "step2_quality_screening/passes_quality_screened_pre_cloud.csv"
)
DEFAULT_VIEWS = RAW / "view_candidate_manifest_latest.csv"
DEFAULT_CACHE = RAW / "enrichment_cmr_cache/l2t"
DEFAULT_MANIFEST = RAW / "enrichment_manifest_cloud_exhaustive.csv"
DEFAULT_OUTPUT = PROCESSED / "step2_quality_screening_exhaustive"
DEFAULT_CLOUD_CHECKPOINT = ASSETS / "cloud_exhaustive_checkpoint.json"
DEFAULT_SHARED_CHECKPOINT = ASSETS / "checkpoint.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _atomic_json(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_dotenv_without_overwrite(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _seed_cloud_checkpoint(
    manifest: pd.DataFrame,
    *,
    cloud_checkpoint: Path,
    shared_checkpoint: Path,
) -> None:
    """Copy only target cloud evidence into the dedicated append-only ledger."""

    target_ids = set(manifest["item_id"].astype(str))
    dedicated = load_checkpoint(cloud_checkpoint)
    shared = load_checkpoint(shared_checkpoint) if shared_checkpoint.is_file() else {}
    changed = False
    for item_id in sorted(target_ids):
        if item_id not in dedicated and item_id in shared:
            dedicated[item_id] = shared[item_id]
            changed = True
    if changed or not cloud_checkpoint.exists():
        write_checkpoint(cloud_checkpoint, dedicated)


def _download_clouds(
    manifest: pd.DataFrame,
    *,
    asset_root: Path,
    checkpoint: Path,
    max_workers: int,
) -> tuple[int, int]:
    """Authenticate non-interactively and fetch only unresolved cloud COGs."""

    _load_dotenv_without_overwrite(ROOT / ".env")
    import earthaccess

    has_environment = bool(
        os.environ.get("EARTHDATA_TOKEN")
        or (
            os.environ.get("EARTHDATA_USERNAME")
            and os.environ.get("EARTHDATA_PASSWORD")
        )
    )
    strategy = "environment" if has_environment else "netrc"
    auth = earthaccess.login(strategy=strategy)
    if not getattr(auth, "authenticated", False):
        raise RuntimeError("Earthdata authentication was not established")
    results = download_target_manifest_concurrent(
        manifest,
        destination_root=asset_root,
        checkpoint_path=checkpoint,
        session_factory=earthaccess.get_requests_https_session,
        max_workers=max_workers,
        checkpoint_batch_size=100,
        timeout_seconds=180,
    )
    downloaded = [result for result in results if not result.cached]
    return len(downloaded), int(sum(result.size_bytes for result in downloaded))


def _domain_geometries() -> dict[str, dict[str, Any]]:
    config = load_config(ROOT / "configs/v2_cities.toml")
    features = load_domain_features(
        ROOT / "data/raw/v2/domains/census_urban_areas.geojson", config
    )
    return {city: feature["geometry"] for city, feature in features.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screened-passes", type=Path, default=DEFAULT_SCREENED)
    parser.add_argument("--view-manifest", type=Path, default=DEFAULT_VIEWS)
    parser.add_argument("--l2t-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--asset-root", type=Path, default=ASSETS)
    parser.add_argument("--cloud-checkpoint", type=Path, default=DEFAULT_CLOUD_CHECKPOINT)
    parser.add_argument("--shared-checkpoint", type=Path, default=DEFAULT_SHARED_CHECKPOINT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=12)
    args = parser.parse_args()

    screened = pd.read_csv(args.screened_passes)
    views = pd.read_csv(args.view_manifest)
    l2t_results = load_cached_l2t_results(args.l2t_cache)
    manifest = build_exhaustive_cloud_manifest(
        screened,
        views,
        l2t_results=l2t_results,
        expected_candidate_passes=EXPECTED_CANDIDATE_PASSES,
    )
    if set(manifest["asset_type"].astype(str)) != {CLOUD_COG}:
        raise ValueError("Refusing a remediation manifest containing non-cloud assets")
    _atomic_csv(manifest, args.manifest)
    print(
        f"cloud-only target manifest: {len(manifest)} assets across "
        f"{manifest[['city', 'orbit']].drop_duplicates().shape[0]} passes",
        flush=True,
    )
    if args.manifest_only:
        return 0

    _seed_cloud_checkpoint(
        manifest,
        cloud_checkpoint=args.cloud_checkpoint,
        shared_checkpoint=args.shared_checkpoint,
    )
    target_ids = manifest["item_id"].astype(str).tolist()
    before_items = load_checkpoint(args.cloud_checkpoint)
    pending_before = pending_item_ids(target_ids, before_items)
    cached_sizes = [
        path.stat().st_size
        for path in (args.asset_root / CLOUD_COG).glob("*.tif")
        if path.is_file()
    ]
    median_size = int(pd.Series(cached_sizes).median()) if cached_sizes else 0
    print(
        f"cloud cache before run: {len(target_ids) - len(pending_before)} verified, "
        f"{len(pending_before)} pending; projected pending bytes ~"
        f"{median_size * len(pending_before):,}",
        flush=True,
    )
    if pending_before:
        if not args.download:
            raise FileNotFoundError(
                f"{len(pending_before)} target cloud assets are pending; rerun with --download"
            )
        _download_clouds(
            manifest,
            asset_root=args.asset_root,
            checkpoint=args.cloud_checkpoint,
            max_workers=args.max_workers,
        )
    cloud_items = load_checkpoint(args.cloud_checkpoint)
    pending_after = pending_item_ids(target_ids, cloud_items)
    if pending_after:
        raise RuntimeError(f"Exhaustive cloud fetch remains incomplete: {len(pending_after)}")

    view_items = load_checkpoint(args.shared_checkpoint)
    view_ids = manifest["view_item_id"].astype(str).tolist()
    missing_view_evidence = [item for item in view_ids if item not in view_items]
    if missing_view_evidence:
        raise ValueError(
            f"{len(missing_view_evidence)} selected view assets lack checkpoint evidence"
        )
    summary = run_exhaustive_cloud_audit(
        screened,
        manifest,
        views,
        domain_geometries_wgs84=_domain_geometries(),
        asset_root=args.asset_root,
        cloud_checkpoint_items=cloud_items,
        view_checkpoint_items=view_items,
        expected_candidate_passes=EXPECTED_CANDIDATE_PASSES,
    )
    dependency_diagnostic, independent_cloud_summary = (
        run_cloud_view_dependency_audit(
            screened,
            manifest,
            views,
            domain_geometries_wgs84=_domain_geometries(),
            asset_root=args.asset_root,
            expected_candidate_passes=EXPECTED_CANDIDATE_PASSES,
        )
    )
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "cloud_pass_summary.csv"
    dependency_path = args.output / "cloud_view_mask_dependency_diagnostic.csv"
    independent_path = args.output / "cloud_pass_summary_independent_of_view.csv"
    validation_json_path = args.output / "cloud_exhaustive_validation.json"
    validation_csv_path = args.output / "cloud_exhaustive_validation.csv"
    _atomic_csv(summary, summary_path)
    _atomic_csv(dependency_diagnostic, dependency_path)
    _atomic_csv(independent_cloud_summary, independent_path)
    validation = build_exhaustive_validation(
        summary,
        screened_passes=screened,
        cloud_view_dependency_diagnostic=dependency_diagnostic,
        independent_cloud_pass_summary=independent_cloud_summary,
        diagnostic_artifacts={
            "cloud_view_dependency_diagnostic_path": str(
                dependency_path.resolve().relative_to(ROOT)
            ),
            "cloud_view_dependency_diagnostic_sha256": _sha256(dependency_path),
            "independent_cloud_pass_summary_path": str(
                independent_path.resolve().relative_to(ROOT)
            ),
            "independent_cloud_pass_summary_sha256": _sha256(independent_path),
        },
        expected_cloud_view_layer_pairs=len(manifest),
        expected_candidate_passes=EXPECTED_CANDIDATE_PASSES,
    )
    _atomic_json(validation, validation_json_path)
    _atomic_csv(pd.DataFrame([validation]), validation_csv_path)

    target_cloud_bytes = int(
        sum(int(cloud_items[item_id]["size_bytes"]) for item_id in target_ids)
    )
    shared_items = load_checkpoint(args.shared_checkpoint)
    shared_target_ids = [item_id for item_id in target_ids if item_id in shared_items]
    shared_target_bytes = int(
        sum(int(shared_items[item_id]["size_bytes"]) for item_id in shared_target_ids)
    )
    shared_cloud_sizes = [
        int(record["size_bytes"])
        for record in shared_items.values()
        if record.get("status") == "complete"
        and record.get("local_path")
        and Path(str(record["local_path"])).parent.name == CLOUD_COG
        and record.get("size_bytes") is not None
    ]
    pre_remediation_median_cloud_bytes = (
        int(pd.Series(shared_cloud_sizes).median()) if shared_cloud_sizes else 0
    )
    added_asset_count = int(len(target_ids) - len(shared_target_ids))
    added_asset_bytes = int(target_cloud_bytes - shared_target_bytes)
    run_record = {
        "decision_id": DECISION_ID,
        "scope": "all 107 frozen pre-cloud candidates; cloud/view quality COGs only",
        "cloud_manifest": str(args.manifest.resolve().relative_to(ROOT)),
        "cloud_manifest_sha256": _sha256(args.manifest),
        "pre_cloud_pass_table_sha256": _sha256(args.screened_passes),
        "latest_view_manifest_sha256": _sha256(args.view_manifest),
        "cloud_pass_summary_sha256": _sha256(summary_path),
        "cloud_view_dependency_diagnostic_sha256": _sha256(dependency_path),
        "independent_cloud_pass_summary_sha256": _sha256(independent_path),
        "cloud_validation_json_sha256": _sha256(validation_json_path),
        "n_candidate_passes": int(len(summary)),
        "n_target_cloud_assets": int(len(manifest)),
        "n_target_cloud_assets_preexisting_in_shared_cache": int(
            len(shared_target_ids)
        ),
        "n_target_cloud_assets_added_for_exhaustive_scope": added_asset_count,
        "projected_added_cloud_bytes_before_fetch": int(
            pre_remediation_median_cloud_bytes * added_asset_count
        ),
        "actual_added_cloud_bytes_for_exhaustive_scope": added_asset_bytes,
        "preexisting_target_cloud_bytes": shared_target_bytes,
        "target_cloud_asset_bytes": target_cloud_bytes,
        "view_assets_reused_not_downloaded": int(len(view_ids)),
        "lst_assets_manifested_downloaded_or_opened": 0,
        "cloud_outcome_used_to_select_targets": False,
        "frozen_years": "2018-2025",
        "holdout_status": "UNSELECTED",
        "validation_complete": bool(validation["complete"]),
        "candidate_seal_geometry_only": bool(
            validation["candidate_seal_geometry_only"]
        ),
        "scientific_gate_eligible": bool(validation["scientific_gate_eligible"]),
        "gate_status": validation["gate_status"],
    }
    _atomic_json(run_record, args.output / "run_record.json")
    print(
        f"observed cloud audit: {validation['resolved_candidate_passes']}/"
        f"{validation['expected_candidate_passes']} resolved; planning floor "
        f"{validation['conservative_planning_floor']}; target cloud bytes "
        f"{target_cloud_bytes:,} ({added_asset_bytes:,} added for D0033); "
        f"gate {validation['gate_status']}",
        flush=True,
    )
    if not validation["complete"]:
        raise RuntimeError("D0033 exhaustive cloud validation is incomplete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
