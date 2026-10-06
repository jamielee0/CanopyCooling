#!/usr/bin/env python3
"""Offline tests for the D0042 exact HDF5 download probe."""

from __future__ import annotations

import json

import pandas as pd

from run_v2_step02_l1b_download_probe import _validate
from urban_cooling_v2.step02_l1b_download_probe import (
    HDF5_SIGNATURE,
    classify_download_probe,
    download_host_chain_allowed,
    sanitized_host_chain,
    validate_exact_hdf_target,
)
from urban_cooling_v2.step02_l1b_identity_audit import canonical_identity_urls


GID = "ECOv002_L1B_GEO_11039_006_20200616T201906_0712_02"


def test_exact_target_only() -> None:
    expected = canonical_identity_urls(GID)["hdf_url"]
    assert validate_exact_hdf_target(GID, expected) == expected
    try:
        validate_exact_hdf_target(GID, expected.replace("11039_006", "11039_007"))
    except ValueError:
        pass
    else:
        raise AssertionError("A non-canonical HDF target was accepted")


def test_host_chain_is_allowlisted_and_sanitized() -> None:
    chain = sanitized_host_chain(
        [
            "https://data.lpdaac.earthdatacloud.nasa.gov/x",
            "https://lp-prod-protected.s3.us-west-2.amazonaws.com/x?secret=signed",
        ]
    )
    assert chain == (
        "https://data.lpdaac.earthdatacloud.nasa.gov",
        "https://lp-prod-protected.s3.us-west-2.amazonaws.com",
    )
    assert download_host_chain_allowed(chain)
    assert download_host_chain_allowed(
        (
            "https://data.lpdaac.earthdatacloud.nasa.gov",
            "https://d1nklfio7vscoe.cloudfront.net",
        )
    )
    assert not download_host_chain_allowed(("https://urs.earthdata.nasa.gov",))
    assert not download_host_chain_allowed(("https://other.cloudfront.net",))
    assert not download_host_chain_allowed(("http://data.lpdaac.earthdatacloud.nasa.gov",))


def test_downloadable_requires_signature_and_official_host() -> None:
    common = {
        "http_status": 206,
        "content_range": "bytes 0-7/1024",
        "content_length": "8",
        "content_encoding": "identity",
        "validator_present": True,
        "error_type": "",
    }
    assert (
        classify_download_probe(
            **common, host_chain_allowed=True, prefix=HDF5_SIGNATURE
        )
        == "range_readable_now"
    )
    assert (
        classify_download_probe(**common, host_chain_allowed=False, prefix=HDF5_SIGNATURE)
        == "unsafe_redirect_target"
    )
    assert (
        classify_download_probe(**common, host_chain_allowed=True, prefix=b"<html>!!")
        == "non_hdf_prefix"
    )


def test_malformed_partial_response_fails_closed() -> None:
    base = {
        "http_status": 206,
        "host_chain_allowed": True,
        "content_length": "8",
        "content_encoding": "",
        "validator_present": True,
        "prefix": HDF5_SIGNATURE,
        "error_type": "",
    }
    assert classify_download_probe(**base, content_range="bytes 1-8/1024") == "protocol_invalid"
    assert (
        classify_download_probe(
            **{**base, "http_status": 200}, content_range=""
        )
        == "range_ignored_unverified"
    )


def test_fail_closed_statuses() -> None:
    assert (
        classify_download_probe(
            http_status=404,
            host_chain_allowed=True,
            content_range="",
            content_length="",
            content_encoding="",
            validator_present=False,
            prefix=b"",
            error_type="",
        )
        == "not_downloadable_candidate"
    )
    assert (
        classify_download_probe(
            http_status=None,
            host_chain_allowed=False,
            content_range="",
            content_length="",
            content_encoding="",
            validator_present=False,
            prefix=b"",
            error_type="Timeout",
        )
        == "transient_or_transport"
    )


def test_append_only_retry_uses_requested_decision_labels() -> None:
    probes = pd.DataFrame(
        {
            "download_probe_status": ["range_readable_now"] * 41,
            "control_bracket_valid": [True] * 41,
            "prefix_bytes_read": [8] * 41,
        }
    )
    controls = [
        {"download_probe_status": "range_readable_now"},
        {"download_probe_status": "range_readable_now"},
    ]
    result = _validate(
        probes,
        controls,
        identity_complete=True,
        decision_id="D0045",
        source_gate_decision_id="D0044",
    )
    assert result["decision_id"] == "D0045"
    assert result["source_gate_decision_id"] == "D0044"
    assert result["gate_status"] == "PASS_D0045_DIRECT_DOWNLOADS"


def main() -> int:
    tests = [
        test_exact_target_only,
        test_host_chain_is_allowlisted_and_sanitized,
        test_downloadable_requires_signature_and_official_host,
        test_malformed_partial_response_fails_closed,
        test_fail_closed_statuses,
        test_append_only_retry_uses_requested_decision_labels,
    ]
    for test in tests:
        test()
    print(json.dumps({"passed": len(tests), "failed": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
