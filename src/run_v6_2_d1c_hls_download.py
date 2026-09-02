#!/usr/bin/env python3
"""Download selected HLS assets using a non-logged Earthdata bearer token."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

import requests


REPO = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPO / "deliverables/D1c_hls_inventory_v6_2_20260902/data/hls_download_plan.json"
DEFAULT_OUTPUT = REPO / "data/raw/v2/hls_v2"
DEFAULT_TOKEN_FILE = Path.home() / ".config/urban-tree-cooling/earthdata_token"
TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_token(path: Path) -> str:
    value = os.environ.get("EARTHDATA_TOKEN")
    source = "EARTHDATA_TOKEN"
    if not value:
        if not path.is_file():
            raise FileNotFoundError(
                f"No Earthdata token found. Run: python src/store_earthdata_token.py"
            )
        value = path.read_text(encoding="utf-8")
        source = str(path)
    token = value.strip()
    if not token or any(character.isspace() for character in token) or "\\" in token:
        raise ValueError(f"Invalid token formatting in {source}")
    if not token.startswith("eyJ") or token.count(".") != 2:
        raise ValueError(f"Value in {source} does not look like an Earthdata JWT")
    return token


def requested_assets(row: dict[str, Any], asset_set: str) -> list[tuple[str, str]]:
    assets: list[tuple[str, str]] = []
    if asset_set in ("fmask", "all") and row.get("fmask_url"):
        assets.append(("Fmask", str(row["fmask_url"])))
    if asset_set in ("reflectance", "all"):
        for name, url in sorted(row.get("reflectance_urls", {}).items()):
            if url:
                assets.append((str(name), str(url)))
    return assets


def target_path(output: Path, row: dict[str, Any], url: str) -> Path:
    filename = Path(urlparse(url).path).name
    if not filename:
        raise ValueError(f"Asset URL lacks filename for {row['optical_acquisition_id']}")
    return output / str(row["sensor"]) / str(row["optical_acquisition_id"]) / filename


def validate_tiff(path: Path) -> None:
    if path.stat().st_size <= 4:
        raise ValueError(f"Downloaded file is too small: {path}")
    with path.open("rb") as handle:
        signature = handle.read(4)
    if signature not in TIFF_SIGNATURES:
        raise ValueError(f"Downloaded response is not a TIFF: {path}")


def download_one(
    *,
    row: dict[str, Any],
    asset_name: str,
    url: str,
    output: Path,
    token: str,
    retries: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    destination = target_path(output, row, url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        validate_tiff(destination)
        return {
            "city": row["city"],
            "sensor": row["sensor"],
            "optical_acquisition_id": row["optical_acquisition_id"],
            "source_time": row["source_time"],
            "mgrs_tile": row["mgrs_tile"],
            "asset": asset_name,
            "source_url": url,
            "local_path": str(destination.relative_to(REPO)),
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
            "status": "VERIFIED_EXISTING",
        }
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "urban-tree-cooling-v6.2-hls-download/1.0",
                },
                stream=True,
                timeout=(30, timeout_seconds),
            ) as response:
                if response.status_code in (401, 403):
                    raise PermissionError(
                        f"Earthdata rejected credentials for {row['optical_acquisition_id']} "
                        f"with HTTP {response.status_code}"
                    )
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            validate_tiff(partial)
            partial.replace(destination)
            return {
                "city": row["city"],
                "sensor": row["sensor"],
                "optical_acquisition_id": row["optical_acquisition_id"],
                "source_time": row["source_time"],
                "mgrs_tile": row["mgrs_tile"],
                "asset": asset_name,
                "source_url": url,
                "local_path": str(destination.relative_to(REPO)),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
                "status": "DOWNLOADED_AND_VERIFIED",
            }
        except PermissionError:
            if partial.exists():
                partial.unlink()
            raise
        except Exception as exc:
            last_error = exc
            if partial.exists():
                partial.unlink()
            if attempt < retries:
                time.sleep(min(2**attempt, 10))
    raise RuntimeError(
        f"Failed to download {asset_name} for {row['optical_acquisition_id']}: {last_error}"
    )


def write_manifest(path: Path, rows: list[dict[str, Any]], *, asset_set: str) -> None:
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "asset_set": asset_set,
        "credentials_recorded": False,
        "files": sorted(rows, key=lambda row: (row["sensor"], row["optical_acquisition_id"], row["asset"])),
        "file_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(payload["files"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--asset-set", choices=("fmask", "reflectance", "all"), default="fmask")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    try:
        token = load_token(args.token_file.expanduser())
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if args.limit is not None:
            plan = plan[: args.limit]
        jobs = [
            (row, asset, url)
            for row in plan
            for asset, url in requested_assets(row, args.asset_set)
        ]
        if not jobs:
            raise ValueError("Download plan contains no requested assets")
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {
                executor.submit(
                    download_one,
                    row=row,
                    asset_name=asset,
                    url=url,
                    output=args.output.resolve(),
                    token=token,
                    retries=max(1, args.retries),
                    timeout_seconds=args.timeout_seconds,
                ): (row["optical_acquisition_id"], asset)
                for row, asset, url in jobs
            }
            for future in as_completed(futures):
                results.append(future.result())
        manifest = args.output.resolve() / f"download_manifest_{args.asset_set}.json"
        write_manifest(manifest, results, asset_set=args.asset_set)
    except Exception as exc:
        print(f"HLS download failed closed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "asset_set": args.asset_set,
                "files": len(results),
                "bytes": sum(int(row["bytes"]) for row in results),
                "manifest": str(manifest),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
