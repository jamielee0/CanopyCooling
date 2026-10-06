#!/usr/bin/env python3
"""Offline D0043 correction of the immutable D0042 direct-download evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in os.sys.path:
    os.sys.path.insert(0, str(ROOT / "src"))

from urban_cooling_v2.step02_l1b_download_probe import (
    HDF5_SIGNATURE,
    classify_download_probe,
    download_host_chain_allowed,
)
from urban_cooling_v2.step02_l1b_identity_audit import sha256_file


SOURCE_DECISION_ID = "D0042"
DECISION_ID = "D0043"
RUN_ID = "R0008_D0043_RECLASSIFY"
EXPECTED_SCENES = 41
SOURCE_DIR = ROOT / "data/processed/v2/task1/step2_l1b_identity_refresh_D0042"
OUTPUT_DIR = ROOT / "data/processed/v2/task1/step2_l1b_download_reclassification_D0043"
SOURCE_PROBES = SOURCE_DIR / "direct_download_probe.csv"
SOURCE_CONTROLS = SOURCE_DIR / "direct_download_controls.json"
SOURCE_RUN_RECORD = SOURCE_DIR / "direct_download_run_record.json"
SOURCE_IDENTITY_VALIDATION = SOURCE_DIR / "identity_validation.json"
OUTPUT_PROBES = OUTPUT_DIR / "direct_download_probe_reclassified.csv"
OUTPUT_CONTROLS = OUTPUT_DIR / "direct_download_controls_reclassified.json"
OUTPUT_VALIDATION = OUTPUT_DIR / "direct_download_validation.json"
OUTPUT_RUN_RECORD = OUTPUT_DIR / "run_record.json"


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


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value)


def _verified_prefix(record: Mapping[str, Any]) -> bytes:
    expected_hash = hashlib.sha256(HDF5_SIGNATURE).hexdigest()
    if (
        bool(record.get("hdf5_signature_verified"))
        and int(record.get("prefix_bytes_read", 0)) == len(HDF5_SIGNATURE)
        and _text(record.get("prefix_sha256")) == expected_hash
    ):
        return HDF5_SIGNATURE
    return b""


def _reclassify(record: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(record)
    chain = tuple(
        part for part in _text(record.get("sanitized_host_chain")).split(";") if part
    )
    allowed = download_host_chain_allowed(chain)
    output["source_download_probe_status"] = _text(record.get("download_probe_status"))
    output["host_chain_allowed"] = allowed
    output["download_probe_status"] = classify_download_probe(
        http_status=(
            None
            if _text(record.get("http_status")) == ""
            else int(float(record["http_status"]))
        ),
        host_chain_allowed=allowed,
        content_range=_text(record.get("content_range")),
        content_length=_text(record.get("content_length")),
        content_encoding=_text(record.get("content_encoding")),
        validator_present=bool(
            _text(record.get("etag")) or _text(record.get("version_id"))
        ),
        prefix=_verified_prefix(record),
        error_type=_text(record.get("error_type")),
    )
    output["source_decision_id"] = SOURCE_DECISION_ID
    output["decision_id"] = DECISION_ID
    output["reclassification_utc"] = datetime.now(timezone.utc).isoformat()
    return output


def _verify_source_seal() -> dict[str, Any]:
    run_record = json.loads(SOURCE_RUN_RECORD.read_text(encoding="utf-8"))
    if run_record.get("decision_id") != SOURCE_DECISION_ID:
        raise ValueError("D0042 source run decision changed")
    hashes = run_record.get("artifact_sha256", {})
    for path in (SOURCE_PROBES, SOURCE_CONTROLS):
        expected = hashes.get(str(path.relative_to(ROOT)))
        if expected != sha256_file(path):
            raise ValueError(f"D0042 source artifact hash changed: {path.name}")
    return run_record


def main() -> int:
    if any(
        path.exists()
        for path in (OUTPUT_PROBES, OUTPUT_CONTROLS, OUTPUT_VALIDATION, OUTPUT_RUN_RECORD)
    ):
        raise FileExistsError("D0043 reclassification output already exists; do not overwrite it")
    source_run = _verify_source_seal()
    source_probes = pd.read_csv(SOURCE_PROBES)
    if (
        len(source_probes) != EXPECTED_SCENES
        or source_probes.duplicated(["orbit", "scene"]).any()
        or not source_probes["decision_id"].astype(str).eq(SOURCE_DECISION_ID).all()
        or not source_probes["http_status"].eq(404).all()
    ):
        raise ValueError("D0042 target evidence seal changed")
    control_document = json.loads(SOURCE_CONTROLS.read_text(encoding="utf-8"))
    source_controls = control_document.get("controls")
    if not isinstance(source_controls, list) or len(source_controls) != 2:
        raise ValueError("D0042 control evidence seal changed")
    controls = [_reclassify(record) for record in source_controls]
    controls_valid = all(
        item["download_probe_status"] == "range_readable_now" for item in controls
    ) and (
        controls[0].get("object_size_bytes"),
        controls[0].get("etag"),
        controls[0].get("version_id"),
    ) == (
        controls[1].get("object_size_bytes"),
        controls[1].get("etag"),
        controls[1].get("version_id"),
    )
    probe_rows: list[dict[str, Any]] = []
    for record in source_probes.to_dict("records"):
        output = _reclassify(record)
        if output["download_probe_status"] == "not_downloadable_candidate":
            output["download_probe_status"] = (
                "not_downloadable_at_exact_url_now"
                if controls_valid
                else "indeterminate_control_failed"
            )
        output["control_bracket_valid"] = controls_valid
        probe_rows.append(output)
    probes = pd.DataFrame(probe_rows).sort_values(
        ["orbit", "scene"], kind="stable"
    ).reset_index(drop=True)
    counts = probes["download_probe_status"].astype(str).value_counts().to_dict()
    readable = int(counts.get("range_readable_now", 0))
    direct_complete = bool(
        controls_valid and len(probes) == EXPECTED_SCENES and readable == EXPECTED_SCENES
    )
    identity_validation = json.loads(
        SOURCE_IDENTITY_VALIDATION.read_text(encoding="utf-8")
    )
    identity_complete = bool(identity_validation.get("identity_complete", False))
    validation = {
        "decision_id": DECISION_ID,
        "source_decision_id": SOURCE_DECISION_ID,
        "source_run_id": source_run.get("run_id"),
        "network_requests_performed": 0,
        "expected_scene_count": EXPECTED_SCENES,
        "attempted_scene_count": int(len(probes)),
        "control_bracket_valid": controls_valid,
        "control_statuses": [item["download_probe_status"] for item in controls],
        "status_counts": {str(key): int(value) for key, value in counts.items()},
        "range_readable_now_count": readable,
        "not_downloadable_at_exact_url_now_count": int(
            counts.get("not_downloadable_at_exact_url_now", 0)
        ),
        "all_exact_hdf_downloads_available": direct_complete,
        "identity_gate_complete": identity_complete,
        "gate_status": (
            "PASS_D0043_DIRECT_DOWNLOADS"
            if direct_complete
            else "STOP_D0043_DIRECT_DOWNLOADS_INCOMPLETE"
        ),
        "payload_bytes_retained": 0,
        "geometry_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "downstream_authorized": bool(direct_complete and identity_complete),
    }
    _atomic_csv(probes, OUTPUT_PROBES)
    _atomic_json(
        {
            "decision_id": DECISION_ID,
            "source_decision_id": SOURCE_DECISION_ID,
            "controls": controls,
        },
        OUTPUT_CONTROLS,
    )
    _atomic_json(validation, OUTPUT_VALIDATION)
    artifacts = [OUTPUT_PROBES, OUTPUT_CONTROLS, OUTPUT_VALIDATION]
    run_record = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": DECISION_ID,
        "profile": "offline reclassification of immutable D0042 range-probe evidence",
        "source_artifact_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in (SOURCE_PROBES, SOURCE_CONTROLS, SOURCE_RUN_RECORD)
        },
        "artifact_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path) for path in artifacts
        },
        "validation": validation,
    }
    _atomic_json(run_record, OUTPUT_RUN_RECORD)
    print(
        f"D0043 corrected direct-download result: {readable}/{EXPECTED_SCENES} "
        f"range-readable; {validation['not_downloadable_at_exact_url_now_count']} "
        f"not downloadable now; gate {validation['gate_status']}",
        flush=True,
    )
    return 0 if direct_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())

