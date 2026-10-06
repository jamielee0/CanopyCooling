#!/usr/bin/env python3
"""Identity-only audit helpers for the D0038 L1B GEO archive-gap review.

This module handles metadata and endpoint identities only.  It must never
request an array response or interpret geolocation values.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


DECISION_ID = "D0038"
COLLECTION_CONCEPT_ID = "C2076087338-LPCLOUD"
EXPECTED_MISSING_SCENES = 41
EXPECTED_SELECTED_SIDECARS = 118

_GEO_POINTER_RE = re.compile(
    r"^ECOv002_L1B_GEO_(?P<orbit>\d{5})_(?P<scene>\d{3})_"
    r"(?P<stamp>\d{8}T\d{6})_(?P<build>\d{4})_(?P<revision>\d{2})\.h5$"
)
_ALLOWED_DATA_HOST = "data.lpdaac.earthdatacloud.nasa.gov"
_ALLOWED_OPENDAP_HOST = "opendap.earthdata.nasa.gov"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_geo_pointer(raw_pointer: Any) -> dict[str, Any]:
    """Return the one exact V002 L1B GEO identity in an L2T InputPointer."""

    if not isinstance(raw_pointer, str) or not raw_pointer.strip():
        raise ValueError("L2T InputPointer is missing")
    parts = [part.strip() for part in raw_pointer.split(",") if part.strip()]
    matches = [(part, _GEO_POINTER_RE.fullmatch(part)) for part in parts]
    matches = [(part, match) for part, match in matches if match is not None]
    if len(matches) != 1:
        raise ValueError("L2T InputPointer must contain exactly one V002 L1B GEO file")
    filename, match = matches[0]
    assert match is not None
    granule_id = filename.removesuffix(".h5")
    return {
        "geo_filename": filename,
        "geo_granule_id": granule_id,
        "orbit": int(match.group("orbit")),
        "scene": int(match.group("scene")),
        "stamp": match.group("stamp"),
        "build": int(match.group("build")),
        "revision": int(match.group("revision")),
        "input_pointer_sha256": sha256_text(raw_pointer),
    }


def canonical_identity_urls(granule_id: str) -> dict[str, str]:
    """Construct only the frozen official endpoint templates."""

    if not re.fullmatch(
        r"ECOv002_L1B_GEO_\d{5}_\d{3}_\d{8}T\d{6}_\d{4}_\d{2}",
        str(granule_id),
    ):
        raise ValueError("Unsafe or noncanonical L1B GEO granule identity")
    base = (
        "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
        f"ECO_L1B_GEO.002/{granule_id}/{granule_id}.h5"
    )
    urls = {
        "hdf_url": base,
        "dmrpp_url": base + ".dmrpp",
        "opendap_dmr_url": (
            "https://opendap.earthdata.nasa.gov/collections/"
            f"{COLLECTION_CONCEPT_ID}/granules/{granule_id}.dmr"
        ),
    }
    for label, value in urls.items():
        parsed = urlsplit(value)
        expected_host = (
            _ALLOWED_OPENDAP_HOST if label == "opendap_dmr_url" else _ALLOWED_DATA_HOST
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected_host
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(f"Unsafe D0038 endpoint: {label}")
    return urls


def validate_exact_cmr_response(
    document: Mapping[str, Any], granule_id: str
) -> tuple[int, str]:
    """Validate an exact producer-ID CMR response and return hit evidence."""

    items = document.get("items")
    if not isinstance(items, list):
        raise ValueError("CMR response lacks an item list")
    identifiers: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("CMR item is not mapping-like")
        umm = item.get("umm", {})
        if not isinstance(umm, Mapping):
            raise ValueError("CMR item lacks UMM metadata")
        identifiers.append(str(umm.get("GranuleUR", "")))
    if any(identifier != granule_id for identifier in identifiers):
        raise ValueError("Exact CMR query returned a different granule identity")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return len(identifiers), sha256_text(canonical)


def validate_opendap_dmr(payload: bytes, granule_id: str) -> str:
    """Validate metadata-only DMR structure without reading an array value."""

    if not payload or len(payload) > 2 * 1024 * 1024:
        raise ValueError("Unsafe OPeNDAP DMR response size")
    root = ET.fromstring(payload)
    dataset_name = str(root.attrib.get("name", ""))
    if dataset_name not in {granule_id, granule_id + ".h5"}:
        raise ValueError("OPeNDAP DMR dataset identity mismatch")
    names = {str(element.attrib.get("name", "")) for element in root.iter()}
    required = {"latitude", "longitude", "view_zenith"}
    if not required.issubset(names):
        raise ValueError("OPeNDAP DMR lacks required geometry metadata")
    return sha256_text(payload.decode("utf-8", errors="strict"))


def classify_identity_resolution(
    *,
    cmr_exact_hits: int,
    hdf_status: int | None,
    dmrpp_status: int | None,
    opendap_status: int | None,
    opendap_metadata_valid: bool,
) -> str:
    """Return the D0038 evidence class; never infer availability."""

    endpoints = hdf_status == 200 and dmrpp_status == 200 and opendap_status == 200
    if cmr_exact_hits == 1 and endpoints and opendap_metadata_valid:
        return "verified_exact_cmr"
    if cmr_exact_hits == 0 and endpoints and opendap_metadata_valid:
        return "verified_exact_object_uncataloged"
    return "unresolved_missing"


__all__ = [
    "COLLECTION_CONCEPT_ID",
    "DECISION_ID",
    "EXPECTED_MISSING_SCENES",
    "EXPECTED_SELECTED_SIDECARS",
    "canonical_identity_urls",
    "classify_identity_resolution",
    "extract_geo_pointer",
    "sha256_file",
    "sha256_text",
    "validate_exact_cmr_response",
    "validate_opendap_dmr",
]
