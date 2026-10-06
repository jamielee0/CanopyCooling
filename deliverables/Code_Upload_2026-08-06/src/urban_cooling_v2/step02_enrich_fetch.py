#!/usr/bin/env python3
"""Safe, checkpointed asset acquisition for the Step-2 ECOSTRESS audit.

The catalogue itself is metadata-only.  This adapter turns a caller-supplied,
predeclared target table into a narrow enrichment manifest containing only:

* the tiled L2T JSON sidecar;
* the tiled ``view_zenith`` COG;
* the tiled ``cloud`` COG; and
* the matching L1B GEO DMR++ document.

LST is deliberately absent from the allow-list and is rejected again at the
download boundary.  Source URLs are validated as HTTPS NASA/USGS endpoints,
must not contain credential-shaped query parameters, are excluded from object
representations, and are never written to the checkpoint ledger.  Callers
should likewise avoid printing the manifest's ``source_url`` column.

All network dependencies are injected.  In production, pass an authenticated
``requests``/``earthaccess`` session; unit tests use an in-memory fake session.
"""

from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import pandas as pd

from .step02_enrich import load_checkpoint, write_checkpoint


L2T_JSON = "l2t_json"
VIEW_ZENITH_COG = "view_zenith_cog"
CLOUD_COG = "cloud_cog"
L1B_GEO_DMRPP = "l1b_geo_dmrpp"

DOWNLOADABLE_ASSET_TYPES = (
    L2T_JSON,
    VIEW_ZENITH_COG,
    CLOUD_COG,
    L1B_GEO_DMRPP,
)
_L2T_ASSET_TYPES = (L2T_JSON, VIEW_ZENITH_COG, CLOUD_COG)

# CMR links for the ECOSTRESS products currently resolve beneath NASA or USGS
# hosts.  Keeping this allow-list suffix-based accommodates official service
# subdomains without accepting arbitrary third-party URLs.
OFFICIAL_HOST_SUFFIXES = ("nasa.gov", "usgs.gov")
_SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "awsaccesskeyid",
    "credential",
    "key",
    "password",
    "secret",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
}

_L2T_ID_PATTERN = (
    r"(?P<product_id>"
    r"ECOv(?P<version>\d{3})_L2T_LSTE_"
    r"(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})_"
    r"(?P<tile>[A-Z0-9]{5})_(?P<timestamp>\d{8}T\d{6})_"
    r"(?P<build>\d+)_(?P<revision>\d+)"
    r")"
)
_L2T_ID_RE = re.compile(rf"^{_L2T_ID_PATTERN}$", re.IGNORECASE)
_L2T_FILE_RE = re.compile(
    rf"^{_L2T_ID_PATTERN}"
    r"(?P<suffix>\.json|_view_zenith\.tif|_cloud\.tif)$",
    re.IGNORECASE,
)
_L1B_FILE_RE = re.compile(
    r"^(?P<product_id>"
    r"ECOv(?P<version>\d{3})_L1B_GEO_"
    r"(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})_"
    r"(?P<timestamp>\d{8}T\d{6})_"
    r"(?P<build>\d+)_(?P<revision>\d+)"
    r")(?:\.h5)?\.dmrpp$",
    re.IGNORECASE,
)
_L1B_H5_RE = re.compile(
    r"^(?P<product_id>"
    r"ECOv(?P<version>\d{3})_L1B_GEO_"
    r"(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})_"
    r"(?P<timestamp>\d{8}T\d{6})_"
    r"(?P<build>\d+)_(?P<revision>\d+)"
    r")\.h5$",
    re.IGNORECASE,
)


class AssetManifestError(ValueError):
    """Raised when a target or asset cannot be represented safely."""


class AssetDownloadError(RuntimeError):
    """Raised without echoing a possibly sensitive source URL."""


@dataclasses.dataclass(frozen=True)
class AssetRef:
    """A validated ECOSTRESS enrichment asset.

    ``source_url`` is intentionally excluded from ``repr``.  It remains
    available to the authenticated downloader and to the in-memory manifest.
    """

    asset_type: str
    source_url: str = dataclasses.field(repr=False)
    file_name: str
    product_id: str
    collection_version: int
    orbit: int
    scene: int
    tile: str | None
    acquisition_stamp: str
    build: int
    revision: int

    @property
    def scene_key(self) -> tuple[int, int]:
        return self.orbit, self.scene

    @property
    def selection_rank(self) -> tuple[int, int, int, str, str]:
        """Deterministic latest-product order, highest tuple wins."""

        return (
            self.build,
            self.revision,
            self.collection_version,
            self.acquisition_stamp,
            self.file_name.casefold(),
        )


@dataclasses.dataclass(frozen=True)
class DownloadResult:
    item_id: str
    local_path: Path
    size_bytes: int
    sha256: str
    resumed: bool
    cached: bool


def _safe_url(value: Any) -> str | None:
    """Return a canonical safe data URL, or ``None`` when it is unsuitable."""

    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    host = parsed.hostname.casefold().rstrip(".")
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES):
        return None
    query_names = {name.casefold() for name, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_names & _SENSITIVE_QUERY_NAMES:
        return None
    # Fragments have no role in HTTP retrieval and can accidentally carry
    # client-side state.  Preserve non-sensitive query parameters because some
    # official service endpoints use them for non-credential routing.
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


def _asset_from_url(value: Any) -> AssetRef | None:
    safe = _safe_url(value)
    if safe is None:
        return None
    file_name = unquote(Path(urlsplit(safe).path).name)
    l2t = _L2T_FILE_RE.fullmatch(file_name)
    if l2t:
        suffix = l2t.group("suffix").casefold()
        asset_type = {
            ".json": L2T_JSON,
            "_view_zenith.tif": VIEW_ZENITH_COG,
            "_cloud.tif": CLOUD_COG,
        }[suffix]
        return AssetRef(
            asset_type=asset_type,
            source_url=safe,
            file_name=file_name,
            product_id=l2t.group("product_id"),
            collection_version=int(l2t.group("version")),
            orbit=int(l2t.group("orbit")),
            scene=int(l2t.group("scene")),
            tile=l2t.group("tile").upper(),
            acquisition_stamp=l2t.group("timestamp").upper(),
            build=int(l2t.group("build")),
            revision=int(l2t.group("revision")),
        )
    geo = _L1B_FILE_RE.fullmatch(file_name)
    if geo is None:
        # NASA's official extraction script appends `.dmrpp` to the protected
        # HDF5 URL.  Recent CMR records can omit the DMR++ RelatedUrl even when
        # that documented endpoint is available, so derive only this exact
        # sidecar on the already validated official host.
        h5 = _L1B_H5_RE.fullmatch(file_name)
        if h5 is not None:
            parsed = urlsplit(safe)
            safe = urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path + ".dmrpp", parsed.query, "")
            )
            file_name = file_name + ".dmrpp"
            geo = _L1B_FILE_RE.fullmatch(file_name)
    if geo:
        return AssetRef(
            asset_type=L1B_GEO_DMRPP,
            source_url=safe,
            file_name=file_name,
            product_id=geo.group("product_id"),
            collection_version=int(geo.group("version")),
            orbit=int(geo.group("orbit")),
            scene=int(geo.group("scene")),
            tile=None,
            acquisition_stamp=geo.group("timestamp").upper(),
            build=int(geo.group("build")),
            revision=int(geo.group("revision")),
        )
    return None


def _walk_related_urls(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).casefold())
            if normalized in {"url", "href"} and isinstance(nested, str):
                yield nested
            else:
                yield from _walk_related_urls(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            yield from _walk_related_urls(nested)


def _candidate_urls(result: Any) -> tuple[str, ...]:
    """Read UMM RelatedUrls and earthaccess data_links without emitting them."""

    urls: list[str] = []
    if isinstance(result, Mapping):
        umm: Any = result.get("umm", result.get("UMM", result))
    else:
        umm = getattr(result, "umm", {})
        if callable(umm):
            umm = umm()
    if isinstance(umm, Mapping):
        related = umm.get("RelatedUrls", umm.get("RelatedURLs", ()))
        urls.extend(_walk_related_urls(related))

    data_links = getattr(result, "data_links", None)
    if callable(data_links):
        try:
            returned = data_links()
        except (AttributeError, TypeError):
            returned = ()
        if isinstance(returned, str):
            urls.append(returned)
        elif returned is not None:
            urls.extend(str(value) for value in returned)

    # Some network-free callers represent data links as a normal mapping key.
    if isinstance(result, Mapping):
        represented = result.get("data_links", ())
        if isinstance(represented, str):
            urls.append(represented)
        elif isinstance(represented, Sequence):
            urls.extend(str(value) for value in represented)
    return tuple(urls)


def extract_related_assets(results: Iterable[Any] | Any) -> tuple[AssetRef, ...]:
    """Extract only safe, official ECOSTRESS enrichment assets.

    Unknown layers (including every LST path), unsafe hosts, credential-bearing
    URLs, and duplicates are silently omitted.  The return order is stable.
    """

    if isinstance(results, Mapping) or hasattr(results, "data_links") or hasattr(results, "umm"):
        records: Iterable[Any] = (results,)
    else:
        records = results
    assets: dict[tuple[str, str], AssetRef] = {}
    for result in records:
        for candidate in _candidate_urls(result):
            asset = _asset_from_url(candidate)
            if asset is not None:
                assets[(asset.asset_type, asset.source_url)] = asset
    return tuple(
        sorted(
            assets.values(),
            key=lambda item: (
                item.orbit,
                item.scene,
                item.product_id.casefold(),
                DOWNLOADABLE_ASSET_TYPES.index(item.asset_type),
                item.file_name.casefold(),
            ),
        )
    )


def select_latest_l1b_geo(
    assets: Iterable[AssetRef],
) -> dict[tuple[int, int], AssetRef]:
    """Select one L1B GEO DMR++ per orbit/scene by build then revision."""

    selected: dict[tuple[int, int], AssetRef] = {}
    for asset in assets:
        if asset.asset_type != L1B_GEO_DMRPP:
            continue
        previous = selected.get(asset.scene_key)
        if previous is None or asset.selection_rank > previous.selection_rank:
            selected[asset.scene_key] = asset
    return selected


def _target_product(value: Any) -> re.Match[str]:
    match = _L2T_ID_RE.fullmatch(str(value).strip())
    if match is None:
        raise AssetManifestError(f"Not an official L2T LSTE granule ID: {value!r}")
    return match


def _integer_field(value: Any, name: str) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise AssetManifestError(f"Target {name} must be an integer") from exc
    return number


def _target_records(targets: pd.DataFrame | Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(targets, pd.DataFrame):
        frame = targets.copy()
    else:
        frame = pd.DataFrame(list(targets))
    required = {"city", "granule_id", "orbit", "scene"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise AssetManifestError(f"Target table lacks columns: {missing}")

    records: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        city = str(raw["city"]).strip()
        if not city:
            raise AssetManifestError("Target city must be non-empty")
        product = _target_product(raw["granule_id"])
        orbit = _integer_field(raw["orbit"], "orbit")
        scene = _integer_field(raw["scene"], "scene")
        if orbit != int(product.group("orbit")) or scene != int(product.group("scene")):
            raise AssetManifestError("Target orbit/scene disagrees with its granule ID")
        records.append(
            {
                "city": city,
                "granule_id": product.group("product_id"),
                "orbit": orbit,
                "scene": scene,
                "tile": product.group("tile").upper(),
            }
        )
    unique = {
        (row["city"], row["granule_id"], row["orbit"], row["scene"]): row
        for row in records
    }
    return [unique[key] for key in sorted(unique)]


def _manifest_item_id(city: str, granule_id: str, asset_type: str) -> str:
    digest = hashlib.sha256(f"{city}|{granule_id}|{asset_type}".encode("utf-8")).hexdigest()
    return f"{asset_type}-{digest[:20]}"


def create_target_manifest(
    targets: pd.DataFrame | Iterable[Mapping[str, Any]],
    *,
    l2t_results: Iterable[Any] | Any,
    l1b_geo_results: Iterable[Any] | Any,
    output_csv: str | os.PathLike[str] | None = None,
) -> pd.DataFrame:
    """Create a long-form manifest restricted to the supplied target rows.

    Every target receives four expected rows.  Missing assets remain explicit
    with ``status='missing'`` and no URL, which prevents downstream code from
    confusing absence with a completed enrichment.
    """

    target_rows = _target_records(targets)
    l2t_assets = extract_related_assets(l2t_results)
    l2t_index: dict[tuple[str, str], AssetRef] = {}
    for asset in l2t_assets:
        if asset.asset_type in _L2T_ASSET_TYPES:
            key = (asset.product_id.casefold(), asset.asset_type)
            previous = l2t_index.get(key)
            if previous is None or asset.selection_rank > previous.selection_rank:
                l2t_index[key] = asset
    geo_index = select_latest_l1b_geo(extract_related_assets(l1b_geo_results))

    rows: list[dict[str, Any]] = []
    for target in target_rows:
        for asset_type in DOWNLOADABLE_ASSET_TYPES:
            if asset_type == L1B_GEO_DMRPP:
                asset = geo_index.get((target["orbit"], target["scene"]))
                selection = "latest_build_revision_for_orbit_scene"
            else:
                asset = l2t_index.get((target["granule_id"].casefold(), asset_type))
                selection = "exact_l2t_granule"
            rows.append(
                {
                    **target,
                    "item_id": _manifest_item_id(
                        target["city"], target["granule_id"], asset_type
                    ),
                    "asset_type": asset_type,
                    "status": "available" if asset is not None else "missing",
                    "selection_rule": selection,
                    "selected_product_id": asset.product_id if asset else None,
                    "selected_build": asset.build if asset else pd.NA,
                    "selected_revision": asset.revision if asset else pd.NA,
                    "file_name": asset.file_name if asset else None,
                    "source_url": asset.source_url if asset else None,
                }
            )
    columns = (
        "city",
        "granule_id",
        "orbit",
        "scene",
        "tile",
        "item_id",
        "asset_type",
        "status",
        "selection_rule",
        "selected_product_id",
        "selected_build",
        "selected_revision",
        "file_name",
        "source_url",
    )
    manifest = pd.DataFrame(rows, columns=columns)
    if output_csv is not None:
        destination = Path(output_csv)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        manifest.to_csv(temporary, index=False)
        temporary.replace(destination)
    return manifest


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_cached_result(
    item_id: str,
    checkpoint_items: Mapping[str, Mapping[str, Any]],
) -> DownloadResult | None:
    record = checkpoint_items.get(item_id)
    if not record or record.get("status") != "complete":
        return None
    local_value = record.get("local_path")
    if not local_value:
        return None
    path = Path(str(local_value))
    if not path.is_file() or path.stat().st_size != record.get("size_bytes"):
        return None
    digest = _sha256(path)
    if digest != record.get("sha256"):
        return None
    return DownloadResult(
        item_id=item_id,
        local_path=path,
        size_bytes=path.stat().st_size,
        sha256=digest,
        resumed=False,
        cached=True,
    )


def _download_record(record: Mapping[str, Any]) -> tuple[str, AssetRef]:
    item_id = str(record.get("item_id", "")).strip()
    if not item_id:
        raise AssetManifestError("Manifest row lacks item_id")
    if str(record.get("status", "")).casefold() != "available":
        raise AssetManifestError(f"Manifest item {item_id} is not available")
    expected_type = str(record.get("asset_type", ""))
    if expected_type not in DOWNLOADABLE_ASSET_TYPES:
        raise AssetManifestError(f"Manifest item {item_id} has a forbidden asset type")
    asset = _asset_from_url(record.get("source_url"))
    if asset is None or asset.asset_type != expected_type:
        # This is the final invariant that prevents an LST URL from being
        # smuggled into a row labelled as cloud or view-angle data.
        raise AssetManifestError(f"Manifest item {item_id} has a non-allow-listed file")
    file_name = str(record.get("file_name", ""))
    if file_name and Path(file_name).name != asset.file_name:
        raise AssetManifestError(f"Manifest item {item_id} filename disagrees with its URL")
    return item_id, asset


def download_manifest_asset(
    record: Mapping[str, Any],
    *,
    destination_root: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
    session: Any,
    chunk_size: int = 1024 * 1024,
    timeout_seconds: float = 120,
    max_bytes: int = 512 * 1024 * 1024,
) -> DownloadResult:
    """Download one allow-listed manifest item with restart and SHA-256 proof.

    Authentication belongs to the injected session.  The checkpoint contains
    only status, local path, byte count, and digest.  Network exceptions are
    replaced with an item-scoped error so signed URLs cannot leak through an
    exception string.
    """

    if chunk_size <= 0 or max_bytes <= 0 or timeout_seconds <= 0:
        raise ValueError("chunk_size, max_bytes, and timeout_seconds must be positive")
    item_id, asset = _download_record(record)
    checkpoint = Path(checkpoint_path)
    items = load_checkpoint(checkpoint)
    cached = _verified_cached_result(item_id, items)
    if cached is not None:
        return cached

    root = Path(destination_root)
    directory = root / asset.asset_type
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / asset.file_name
    partial = destination.with_name(f"{destination.name}.part")
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset > max_bytes:
        raise AssetDownloadError(f"Partial file for {item_id} exceeds the byte limit")
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    response: Any = None
    try:
        response = session.get(
            asset.source_url,
            headers=headers,
            stream=True,
            timeout=timeout_seconds,
        )
        status = int(getattr(response, "status_code", 0))
        if status not in {200, 206}:
            raise AssetDownloadError(f"HTTP status {status} for {item_id}")

        resumed = offset > 0 and status == 206
        if resumed:
            content_range = str(getattr(response, "headers", {}).get("Content-Range", ""))
            if content_range and not content_range.casefold().startswith(f"bytes {offset}-"):
                raise AssetDownloadError(f"Invalid resume range for {item_id}")
            mode = "ab"
            total = offset
        else:
            # A server may ignore Range and return 200.  Restarting avoids
            # concatenating the full file after an existing partial prefix.
            mode = "wb"
            total = 0

        content_length = getattr(response, "headers", {}).get("Content-Length")
        if content_length not in (None, ""):
            expected = total + int(content_length)
            if expected > max_bytes:
                raise AssetDownloadError(f"Download for {item_id} exceeds the byte limit")
        else:
            expected = None

        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise AssetDownloadError(f"Download for {item_id} exceeds the byte limit")
                handle.write(chunk)
        if expected is not None and total != expected:
            raise AssetDownloadError(f"Incomplete response for {item_id}")
        partial.replace(destination)
        digest = _sha256(destination)
        items[item_id] = {
            "status": "complete",
            "local_path": str(destination),
            "size_bytes": destination.stat().st_size,
            "sha256": digest,
        }
        write_checkpoint(checkpoint, items)
        return DownloadResult(
            item_id=item_id,
            local_path=destination,
            size_bytes=destination.stat().st_size,
            sha256=digest,
            resumed=resumed,
            cached=False,
        )
    except AssetDownloadError:
        if partial.is_file():
            items[item_id] = {
                "status": "partial",
                "local_path": str(partial),
                "size_bytes": partial.stat().st_size,
            }
            write_checkpoint(checkpoint, items)
        raise
    except Exception:
        if partial.is_file():
            items[item_id] = {
                "status": "partial",
                "local_path": str(partial),
                "size_bytes": partial.stat().st_size,
            }
            write_checkpoint(checkpoint, items)
        raise AssetDownloadError(f"Download failed for {item_id}") from None
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def download_target_manifest(
    manifest: pd.DataFrame,
    *,
    destination_root: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
    session: Any,
    **download_kwargs: Any,
) -> list[DownloadResult]:
    """Download available manifest rows in stable order; skip explicit misses."""

    required = {"item_id", "asset_type", "status", "file_name", "source_url"}
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise AssetManifestError(f"Manifest lacks columns: {missing}")
    rows = manifest.loc[manifest["status"].astype(str).str.casefold() == "available"].copy()
    rows = rows.sort_values(["asset_type", "item_id"], kind="stable")
    return [
        download_manifest_asset(
            row,
            destination_root=destination_root,
            checkpoint_path=checkpoint_path,
            session=session,
            **download_kwargs,
        )
        for row in rows.to_dict("records")
    ]


def download_target_manifest_concurrent(
    manifest: pd.DataFrame,
    *,
    destination_root: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
    session_factory: Any,
    max_workers: int = 12,
    checkpoint_batch_size: int = 100,
    **download_kwargs: Any,
) -> list[DownloadResult]:
    """Download independent assets concurrently with race-free checkpoints.

    Each item uses its own small ledger while workers run.  The coordinating
    thread consolidates verified file evidence into the requested checkpoint
    after every batch, so interruption loses at most scheduling state—not a
    completed file.  Authentication sessions are thread-local and never
    serialized.
    """

    if max_workers < 1 or checkpoint_batch_size < 1:
        raise ValueError("max_workers and checkpoint_batch_size must be positive")
    required = {"item_id", "asset_type", "status", "file_name", "source_url"}
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise AssetManifestError(f"Manifest lacks columns: {missing}")
    rows = manifest.loc[
        manifest["status"].astype(str).str.casefold() == "available"
    ].sort_values(["asset_type", "item_id"], kind="stable")
    records = rows.to_dict("records")
    root = Path(destination_root)
    item_checkpoint_dir = root / ".item_checkpoints"
    item_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    consolidated = load_checkpoint(checkpoint_path)
    local = threading.local()

    def worker(record: Mapping[str, Any]) -> DownloadResult:
        cached = _verified_cached_result(str(record["item_id"]), consolidated)
        if cached is not None:
            return cached
        if not hasattr(local, "session"):
            local.session = session_factory()
        item_id = str(record["item_id"])
        return download_manifest_asset(
            record,
            destination_root=root,
            checkpoint_path=item_checkpoint_dir / f"{item_id}.json",
            session=local.session,
            **download_kwargs,
        )

    completed: list[DownloadResult] = []
    for start in range(0, len(records), checkpoint_batch_size):
        batch = records[start : start + checkpoint_batch_size]
        failures: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, record): record for record in batch}
            for future in as_completed(futures):
                record = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    failures.append((str(record["item_id"]), type(exc).__name__))
                    continue
                completed.append(result)
                consolidated[result.item_id] = {
                    "status": "complete",
                    "local_path": str(result.local_path),
                    "size_bytes": result.size_bytes,
                    "sha256": result.sha256,
                }
        write_checkpoint(checkpoint_path, consolidated)
        if failures:
            preview = ", ".join(f"{item}:{kind}" for item, kind in failures[:10])
            raise AssetDownloadError(
                f"{len(failures)} concurrent enrichment download(s) failed: {preview}"
            )
    return completed


__all__ = [
    "AssetDownloadError",
    "AssetManifestError",
    "AssetRef",
    "CLOUD_COG",
    "DOWNLOADABLE_ASSET_TYPES",
    "DownloadResult",
    "L1B_GEO_DMRPP",
    "L2T_JSON",
    "VIEW_ZENITH_COG",
    "create_target_manifest",
    "download_manifest_asset",
    "download_target_manifest",
    "download_target_manifest_concurrent",
    "extract_related_assets",
    "select_latest_l1b_geo",
]
