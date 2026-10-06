#!/usr/bin/env python3
"""Retry the 41 exact L1B GEO HDF5 objects with an eight-byte range download."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in os.sys.path:
    os.sys.path.insert(0, str(ROOT / "src"))

from run_v2_step02_l1b_geometry import _earthaccess
from urban_cooling_v2.step02_l1b_download_probe import (
    CONTENT_RANGE_PATTERN,
    EXPECTED_RANGE,
    HDF5_SIGNATURE,
    classify_download_probe,
    download_host_chain_allowed,
    sanitized_host_chain,
    validate_exact_hdf_target,
)
from urban_cooling_v2.step02_l1b_identity_audit import (
    canonical_identity_urls,
    sha256_file,
)


DECISION_ID = "D0042"
RUN_ID = "R0007_D0042_RANGE"
EXPECTED_SCENES = 41
DEFAULT_INPUT = (
    ROOT
    / "data/processed/v2/task1/step2_l1b_identity_refresh_D0042/scene_identity_resolution.csv"
)
DEFAULT_OUTPUT_DIR = (
    ROOT / "data/processed/v2/task1/step2_l1b_identity_refresh_D0042"
)
PROBE_CSV = "direct_download_probe.csv"
CONTROLS_JSON = "direct_download_controls.json"
VALIDATION_JSON = "direct_download_validation.json"
RUN_RECORD_JSON = "direct_download_run_record.json"
RANGE_HEADER = EXPECTED_RANGE
CONTROL_GID = "ECOv002_L1B_GEO_11039_007_20200616T201958_0712_02"
CONTROL_URL = canonical_identity_urls(CONTROL_GID)["hdf_url"]


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


def _load_exact_targets(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path)
    required = {
        "orbit",
        "scene",
        "geo_granule_id",
        "hdf_url",
        "decision_id",
        "geometry_values_opened",
    }
    if not required.issubset(table.columns):
        raise ValueError("D0042 identity resolution lacks required columns")
    if (
        len(table) != EXPECTED_SCENES
        or table.duplicated(["orbit", "scene"]).any()
        or table["geo_granule_id"].astype(str).duplicated().any()
        or not table["decision_id"].astype(str).eq(DECISION_ID).all()
        or not table["geometry_values_opened"].astype(str).str.casefold().eq("false").all()
    ):
        raise ValueError("D0042 exact-scene input seal changed")
    for row in table.to_dict("records"):
        validate_exact_hdf_target(str(row["geo_granule_id"]), str(row["hdf_url"]))
    return table.sort_values(["orbit", "scene"], kind="stable").reset_index(drop=True)


def _probe_one(
    record: Mapping[str, Any],
    *,
    client: Any,
    role: str,
    decision_id: str = DECISION_ID,
) -> dict[str, Any]:
    response = None
    prefix = b""
    http_status: int | None = None
    host_chain: tuple[str, ...] = ()
    content_range = ""
    content_length = ""
    content_type = ""
    content_encoding = ""
    etag = ""
    version_id = ""
    error_type = ""
    try:
        response = client.get(
            str(record["hdf_url"]),
            headers={
                "Range": RANGE_HEADER,
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
            },
            allow_redirects=True,
            stream=True,
            timeout=(30, 120),
        )
        http_status = int(response.status_code)
        host_chain = sanitized_host_chain(
            [str(item.url) for item in response.history] + [str(response.url)]
        )
        content_range = str(response.headers.get("Content-Range", ""))
        content_length = str(response.headers.get("Content-Length", ""))
        content_type = str(response.headers.get("Content-Type", ""))
        content_encoding = str(response.headers.get("Content-Encoding", ""))
        etag = str(response.headers.get("ETag", ""))
        version_id = str(response.headers.get("x-amz-version-id", ""))
        if http_status == 206:
            prefix = response.raw.read(len(HDF5_SIGNATURE), decode_content=False)
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        if response is not None:
            response.close()
    chain_allowed = download_host_chain_allowed(host_chain)
    status = classify_download_probe(
        http_status=http_status,
        host_chain_allowed=chain_allowed,
        content_range=content_range,
        content_length=content_length,
        content_encoding=content_encoding,
        validator_present=bool(etag or version_id),
        prefix=prefix,
        error_type=error_type,
    )
    match = CONTENT_RANGE_PATTERN.fullmatch(content_range.strip())
    return {
        "probe_role": role,
        "orbit": int(record["orbit"]),
        "scene": int(record["scene"]),
        "geo_granule_id": str(record["geo_granule_id"]),
        "hdf_url": str(record["hdf_url"]),
        "range_header": RANGE_HEADER,
        "http_status": http_status,
        "redirect_count": max(0, len(host_chain) - 1),
        "sanitized_host_chain": ";".join(host_chain),
        "host_chain_allowed": chain_allowed,
        "content_range": content_range,
        "content_length": content_length,
        "content_type": content_type,
        "content_encoding": content_encoding,
        "etag": etag,
        "version_id": version_id,
        "object_size_bytes": int(match.group(1)) if match else None,
        "prefix_bytes_read": len(prefix),
        "prefix_sha256": hashlib.sha256(prefix).hexdigest() if prefix else "",
        "hdf5_signature_verified": prefix == HDF5_SIGNATURE,
        "error_type": error_type,
        "download_probe_status": status,
        "payload_bytes_retained": 0,
        "geometry_values_opened": False,
        "lst_opened": False,
        "record_2026_opened": False,
        "decision_id": decision_id,
        "retrieval_utc": datetime.now(timezone.utc).isoformat(),
    }


def _probe_targets(
    targets: pd.DataFrame,
    *,
    session_factory: Any,
    max_workers: int,
    decision_id: str = DECISION_ID,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    control_record = {
        "orbit": 11039,
        "scene": 7,
        "geo_granule_id": CONTROL_GID,
        "hdf_url": CONTROL_URL,
    }
    control_client = session_factory()
    pre_control = _probe_one(
        control_record,
        client=control_client,
        role="control_before",
        decision_id=decision_id,
    )

    local = threading.local()

    def session() -> Any:
        if not hasattr(local, "value"):
            local.value = session_factory()
        return local.value

    def worker(record: Mapping[str, Any]) -> dict[str, Any]:
        return _probe_one(
            record,
            client=session(),
            role="target",
            decision_id=decision_id,
        )

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(worker, record): (int(record["orbit"]), int(record["scene"]))
            for record in targets.to_dict("records")
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                raise RuntimeError(f"Direct-download worker failed for {key}") from exc
    post_control = _probe_one(
        control_record,
        client=control_client,
        role="control_after",
        decision_id=decision_id,
    )
    controls = [pre_control, post_control]
    controls_valid = all(
        item["download_probe_status"] == "range_readable_now" for item in controls
    ) and (
        pre_control["object_size_bytes"], pre_control["etag"], pre_control["version_id"]
    ) == (
        post_control["object_size_bytes"], post_control["etag"], post_control["version_id"]
    )
    for row in rows:
        if row["download_probe_status"] == "not_downloadable_candidate":
            row["download_probe_status"] = (
                "not_downloadable_at_exact_url_now"
                if controls_valid
                else "indeterminate_control_failed"
            )
        row["control_bracket_valid"] = controls_valid
    probes = pd.DataFrame(rows).sort_values(
        ["orbit", "scene"], kind="stable"
    ).reset_index(drop=True)
    return probes, controls

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(worker, record): (int(record["orbit"]), int(record["scene"]))
            for record in targets.to_dict("records")
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                raise RuntimeError(f"Direct-download worker failed for {key}") from exc
    return pd.DataFrame(rows).sort_values(["orbit", "scene"], kind="stable").reset_index(
        drop=True
    )


def _validate(
    probes: pd.DataFrame,
    controls: list[dict[str, Any]],
    *,
    identity_complete: bool,
    decision_id: str = DECISION_ID,
    source_gate_decision_id: str = "D0041",
) -> dict[str, Any]:
    counts = probes["download_probe_status"].astype(str).value_counts().to_dict()
    downloadable = int(counts.get("range_readable_now", 0))
    controls_valid = bool(
        len(controls) == 2
        and all(item["download_probe_status"] == "range_readable_now" for item in controls)
        and probes["control_bracket_valid"].astype(bool).all()
    )
    complete = bool(
        controls_valid
        and len(probes) == EXPECTED_SCENES
        and downloadable == EXPECTED_SCENES
    )
    return {
        "decision_id": decision_id,
        "source_gate_decision_id": source_gate_decision_id,
        "expected_scene_count": EXPECTED_SCENES,
        "attempted_scene_count": int(len(probes)),
        "control_bracket_valid": controls_valid,
        "control_statuses": [str(item["download_probe_status"]) for item in controls],
        "status_counts": {str(key): int(value) for key, value in counts.items()},
        "range_readable_now_count": downloadable,
        "not_downloadable_at_exact_url_now_count": int(
            counts.get("not_downloadable_at_exact_url_now", 0)
        ),
        "transient_or_transport_count": int(counts.get("transient_or_transport", 0)),
        "all_exact_hdf_downloads_available": complete,
        "identity_gate_complete": bool(identity_complete),
        "gate_status": (
            f"PASS_{decision_id}_DIRECT_DOWNLOADS"
            if complete
            else f"STOP_{decision_id}_DIRECT_DOWNLOADS_INCOMPLETE"
        ),
        "maximum_payload_bytes_read_per_scene": int(probes["prefix_bytes_read"].max()),
        "payload_bytes_retained": 0,
        "geometry_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "downstream_authorized": bool(complete and identity_complete),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--decision-id", default=DECISION_ID)
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--source-gate-decision-id", default="D0041")
    args = parser.parse_args()
    if not 1 <= args.max_workers <= 8:
        raise ValueError("max-workers must be between 1 and 8")
    if not args.decision_id.startswith("D") or not args.decision_id[1:].isdigit():
        raise ValueError("decision-id must use the D#### form")
    if not args.run_id.startswith("R"):
        raise ValueError("run-id must start with R")
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    task1_root = (ROOT / "data/processed/v2/task1").resolve()
    if output_dir == task1_root or task1_root not in output_dir.parents:
        raise ValueError("Direct-download output must be within the v2 Task 1 tree")
    probe_path = output_dir / PROBE_CSV
    controls_path = output_dir / CONTROLS_JSON
    validation_path = output_dir / VALIDATION_JSON
    run_record_path = output_dir / RUN_RECORD_JSON
    if any(
        path.exists()
        for path in (probe_path, controls_path, validation_path, run_record_path)
    ):
        raise FileExistsError("Direct-download evidence already exists; do not overwrite it")
    targets = _load_exact_targets(input_path)
    identity_validation_path = input_path.with_name("identity_validation.json")
    identity_validation = json.loads(identity_validation_path.read_text(encoding="utf-8"))
    if identity_validation.get("decision_id") != DECISION_ID:
        raise ValueError("D0042 identity validation seal changed")
    earthaccess, _ = _earthaccess()
    probes, controls = _probe_targets(
        targets,
        session_factory=earthaccess.get_requests_https_session,
        max_workers=args.max_workers,
        decision_id=args.decision_id,
    )
    validation = _validate(
        probes,
        controls,
        identity_complete=bool(identity_validation.get("identity_complete", False)),
        decision_id=args.decision_id,
        source_gate_decision_id=args.source_gate_decision_id,
    )
    _atomic_csv(probes, probe_path)
    _atomic_json({"decision_id": args.decision_id, "controls": controls}, controls_path)
    _atomic_json(validation, validation_path)
    artifacts = [probe_path, controls_path, validation_path]
    run_record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": args.decision_id,
        "profile": "authenticated exact HDF5 bytes=0-7 streaming download probe",
        "input_resolution_path": str(input_path.relative_to(ROOT)),
        "input_resolution_sha256": sha256_file(input_path),
        "identity_validation_path": str(identity_validation_path.relative_to(ROOT)),
        "identity_validation_sha256": sha256_file(identity_validation_path),
        "artifact_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path) for path in artifacts
        },
        "validation": validation,
    }
    _atomic_json(run_record, run_record_path)
    print(
        f"{args.decision_id} direct-download retry: {validation['range_readable_now_count']}/"
        f"{EXPECTED_SCENES} exact HDF5 objects downloadable; gate {validation['gate_status']}",
        flush=True,
    )
    return 0 if validation["all_exact_hdf_downloads_available"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
