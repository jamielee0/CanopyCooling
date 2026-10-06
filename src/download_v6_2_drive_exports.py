#!/usr/bin/env python3
"""Download and verify the frozen pre-Gate-A TCC and 3DEP Drive exports.

The script uses the already-authorized Earth Engine OAuth credential, which includes
Google Drive scope.  It never opens ECOSTRESS thermal or HLS reflectance data.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import ee
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


ROOT = Path(__file__).resolve().parents[1]
DRIVE_FOLDER_ID = "1BWuKX2np0_cTVPvVpiFCQXq5Ip6whU1R"
EE_PROJECT = "tree-497018"

GROUPS = {
    "science_tcc": {
        "prefix": "science_tcc_v2025-6_",
        "expected_count": 14,
        "expected_bytes": 211_808_618,
        "output_dir": ROOT / "data/raw/v2/science_tcc_v2025_6/drive_exports",
        "manifest": ROOT / "data/raw/v2/science_tcc_v2025_6/drive_output_verification.json",
    },
    "usgs_3dep": {
        "prefix": "usgs_3dep_10m_",
        "expected_count": 2,
        "expected_bytes": 426_375_529,
        "output_dir": ROOT / "data/raw/v2/usgs_3dep_10m/drive_exports",
        "manifest": ROOT / "data/raw/v2/usgs_3dep_10m/drive_output_verification.json",
    },
}


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def list_drive_files(service: Any) -> list[dict[str, Any]]:
    fields = (
        "nextPageToken,files(id,name,mimeType,size,md5Checksum,sha1Checksum,"
        "sha256Checksum,createdTime,modifiedTime,parents)"
    )
    files: list[dict[str, Any]] = []
    token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{DRIVE_FOLDER_ID}' in parents and trashed = false",
                fields=fields,
                pageSize=1000,
                pageToken=token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            return files


def download(service: Any, file_id: str, output_path: Path, expected_size: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size == expected_size:
        return
    partial = output_path.with_suffix(output_path.suffix + ".partial")
    request = service.files().get_media(fileId=file_id)
    with partial.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    if partial.stat().st_size != expected_size:
        raise RuntimeError(
            f"size mismatch for {output_path.name}: {partial.stat().st_size} != {expected_size}"
        )
    os.replace(partial, output_path)


def verify_group(service: Any, drive_files: list[dict[str, Any]], name: str, spec: dict[str, Any]) -> None:
    selected = sorted(
        (
            row
            for row in drive_files
            if row["name"].startswith(spec["prefix"])
            and row["name"].lower().endswith((".tif", ".tiff"))
        ),
        key=lambda row: row["name"],
    )
    if len(selected) != spec["expected_count"]:
        raise RuntimeError(f"{name}: expected {spec['expected_count']} files, found {len(selected)}")
    if sum(int(row["size"]) for row in selected) != spec["expected_bytes"]:
        raise RuntimeError(f"{name}: Drive aggregate byte count changed")

    verified = []
    for row in selected:
        output_path = spec["output_dir"] / row["name"]
        expected_size = int(row["size"])
        download(service, row["id"], output_path, expected_size)
        local_md5 = digest(output_path, "md5")
        local_sha256 = digest(output_path, "sha256")
        if row.get("md5Checksum") and local_md5 != row["md5Checksum"]:
            raise RuntimeError(f"{name}: Google MD5 mismatch for {row['name']}")
        verified.append(
            {
                "name": row["name"],
                "drive_file_id": row["id"],
                "drive_url": f"https://drive.google.com/file/d/{row['id']}/view",
                "mime_type": row["mimeType"],
                "bytes": expected_size,
                "google_md5": row.get("md5Checksum"),
                "local_md5": local_md5,
                "local_sha256": local_sha256,
                "local_path": str(output_path.relative_to(ROOT)),
                "created_time": row.get("createdTime"),
                "modified_time": row.get("modifiedTime"),
                "download_verified": True,
            }
        )

    record = {
        "schema_version": "1.0",
        "group": name,
        "drive_folder_id": DRIVE_FOLDER_ID,
        "file_count": len(verified),
        "total_bytes": sum(row["bytes"] for row in verified),
        "all_google_md5_match": all(
            row["google_md5"] is not None and row["google_md5"] == row["local_md5"]
            for row in verified
        ),
        "thermal_or_hls_reflectance_accessed": False,
        "files": verified,
    }
    spec["manifest"].parent.mkdir(parents=True, exist_ok=True)
    spec["manifest"].write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: record[key] for key in ("group", "file_count", "total_bytes", "all_google_md5_match")}))


def main() -> None:
    ee.Initialize(project=EE_PROJECT)
    credentials = ee.data.get_persistent_credentials()
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    drive_files = list_drive_files(service)
    for name, spec in GROUPS.items():
        verify_group(service, drive_files, name, spec)


if __name__ == "__main__":
    main()
