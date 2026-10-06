"""Fail-closed helpers for tiny direct-download probes of exact L1B GEO objects."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from urban_cooling_v2.step02_l1b_identity_audit import canonical_identity_urls


HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
EXPECTED_RANGE = f"bytes=0-{len(HDF5_SIGNATURE) - 1}"
CONTENT_RANGE_PATTERN = re.compile(
    rf"bytes\s+0-{len(HDF5_SIGNATURE) - 1}/([1-9][0-9]*)", re.IGNORECASE
)
ALLOWED_FINAL_HOSTS = frozenset(
    {
        "data.lpdaac.earthdatacloud.nasa.gov",
        "d1nklfio7vscoe.cloudfront.net",
        "lp-prod-protected.s3.amazonaws.com",
        "lp-prod-protected.s3.us-west-2.amazonaws.com",
    }
)


def validate_exact_hdf_target(granule_id: str, hdf_url: str) -> str:
    """Require the canonical protected-object URL for the exact granule identity."""

    expected = canonical_identity_urls(granule_id)["hdf_url"]
    if hdf_url != expected:
        raise ValueError("Direct-download target is not the canonical exact HDF5 URL")
    return expected


def sanitized_host_chain(urls: list[str]) -> tuple[str, ...]:
    """Return only schemes/hosts, deliberately discarding signed paths and queries."""

    output: list[str] = []
    for value in urls:
        parsed = urlparse(value)
        host = (parsed.hostname or "").casefold()
        output.append(f"{parsed.scheme.casefold()}://{host}")
    return tuple(output)


def download_host_chain_allowed(host_chain: tuple[str, ...]) -> bool:
    if not host_chain:
        return False
    for value in host_chain:
        parsed = urlparse(value)
        if parsed.scheme != "https" or (parsed.hostname or "") not in ALLOWED_FINAL_HOSTS:
            return False
    return True


def classify_download_probe(
    *,
    http_status: int | None,
    host_chain_allowed: bool,
    content_range: str,
    content_length: str,
    content_encoding: str,
    validator_present: bool,
    prefix: bytes,
    error_type: str,
) -> str:
    """Classify a bounded range response without treating login HTML as data."""

    if error_type:
        return "transient_or_transport"
    if http_status in {404, 410}:
        return "not_downloadable_candidate"
    if http_status in {401, 403}:
        return "auth_or_access_failure"
    if http_status == 200:
        return "range_ignored_unverified"
    if http_status == 416 or http_status == 204:
        return "invalid_object_response"
    if http_status == 429 or (http_status is not None and http_status >= 500):
        return "transient_or_transport"
    if http_status != 206:
        return "unexpected_http_status"
    if not host_chain_allowed:
        return "unsafe_redirect_target"
    match = CONTENT_RANGE_PATTERN.fullmatch(content_range.strip())
    if match is None or int(match.group(1)) <= len(HDF5_SIGNATURE):
        return "protocol_invalid"
    if content_length.strip() not in {"", str(len(HDF5_SIGNATURE))}:
        return "protocol_invalid"
    if content_encoding.strip().casefold() not in {"", "identity"}:
        return "protocol_invalid"
    if not validator_present:
        return "protocol_invalid"
    if len(prefix) != len(HDF5_SIGNATURE) or prefix != HDF5_SIGNATURE:
        return "non_hdf_prefix"
    return "range_readable_now"
