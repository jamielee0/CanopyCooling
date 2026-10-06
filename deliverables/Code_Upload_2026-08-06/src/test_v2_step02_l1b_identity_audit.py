#!/usr/bin/env python3
"""Offline regression tests for the D0038 metadata-only identity audit."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from run_v2_step02_l1b_identity_audit import (
    ROOT,
    _validated_output_dir,
    _validation,
)

from urban_cooling_v2.step02_l1b_identity_audit import (
    canonical_identity_urls,
    classify_identity_resolution,
    extract_geo_pointer,
    validate_exact_cmr_response,
    validate_opendap_dmr,
)


GID = "ECOv002_L1B_GEO_11039_006_20200616T201906_0712_02"


def test_extract_pointer_requires_one_exact_geo() -> None:
    value = (
        "ECOv002_L2_LSTE_11039_006_20200616T201906_0712_02.h5,"
        f"{GID}.h5,ECOv002_L1B_RAD_11039_006_20200616T201906_0712_02.h5"
    )
    result = extract_geo_pointer(value)
    assert result["geo_granule_id"] == GID
    assert (result["orbit"], result["scene"], result["build"], result["revision"]) == (
        11039,
        6,
        712,
        2,
    )
    for bad in ("", "../x.h5", f"{GID}.h5,{GID}.h5"):
        try:
            extract_geo_pointer(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe or ambiguous InputPointer was accepted")


def test_urls_are_exact_official_metadata_endpoints() -> None:
    urls = canonical_identity_urls(GID)
    assert urls["hdf_url"].endswith(f"/{GID}/{GID}.h5")
    assert urls["dmrpp_url"] == urls["hdf_url"] + ".dmrpp"
    assert urls["opendap_dmr_url"].endswith(f"/{GID}.dmr")
    assert all("?" not in value for value in urls.values())
    try:
        canonical_identity_urls("../../secret")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe granule identity was accepted")


def test_exact_cmr_response_rejects_other_identity() -> None:
    empty = {"items": []}
    assert validate_exact_cmr_response(empty, GID)[0] == 0
    exact = {"items": [{"umm": {"GranuleUR": GID}}]}
    assert validate_exact_cmr_response(exact, GID)[0] == 1
    wrong = {"items": [{"umm": {"GranuleUR": GID.replace("006", "007", 1)}}]}
    try:
        validate_exact_cmr_response(wrong, GID)
    except ValueError:
        pass
    else:
        raise AssertionError("different CMR identity was accepted")


def test_dmr_validation_reads_metadata_only() -> None:
    payload = (
        f'<Dataset name="{GID}"><Group name="Geolocation">'
        '<Float64 name="latitude"/><Float64 name="longitude"/>'
        '<Float32 name="view_zenith"/></Group></Dataset>'
    ).encode()
    assert len(validate_opendap_dmr(payload, GID)) == 64
    missing = payload.replace(b' name="view_zenith"', b' name="height"')
    try:
        validate_opendap_dmr(missing, GID)
    except ValueError:
        pass
    else:
        raise AssertionError("DMR missing view_zenith was accepted")


def test_classification_is_fail_closed() -> None:
    common = dict(
        hdf_status=200,
        dmrpp_status=200,
        opendap_status=200,
        opendap_metadata_valid=True,
    )
    assert classify_identity_resolution(cmr_exact_hits=1, **common) == "verified_exact_cmr"
    assert (
        classify_identity_resolution(cmr_exact_hits=0, **common)
        == "verified_exact_object_uncataloged"
    )
    assert (
        classify_identity_resolution(
            cmr_exact_hits=1,
            hdf_status=404,
            dmrpp_status=404,
            opendap_status=404,
            opendap_metadata_valid=False,
        )
        == "unresolved_missing"
    )


def test_refresh_validation_uses_new_decision_identity() -> None:
    resolution = pd.DataFrame(
        {
            "identity_resolution_status": ["verified_exact_cmr"] * 41,
            "hdf_http_status": [200] * 41,
            "dmrpp_http_status": [200] * 41,
            "opendap_dmr_http_status": [200] * 41,
        }
    )
    evidence = pd.DataFrame({"row": range(118)})
    result = _validation(
        resolution,
        evidence,
        decision_id="D0040",
        source_gate_decision_id="D0039",
    )
    assert result["gate_status"] == "PASS_D0040_EXACT_IDENTITIES"
    assert result["source_gate_decision_id"] == "D0039"
    assert result["downstream_authorized"] is True


def test_refresh_output_must_stay_in_task1_tree() -> None:
    expected = (ROOT / "data/processed/v2/task1/step2_refresh_D0040").resolve()
    assert _validated_output_dir(Path("data/processed/v2/task1/step2_refresh_D0040")) == expected
    for bad in (Path("/tmp/d0040"), ROOT / "data/processed/v2/task1"):
        try:
            _validated_output_dir(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("out-of-scope identity-audit output was accepted")


def main() -> int:
    tests = [
        test_extract_pointer_requires_one_exact_geo,
        test_urls_are_exact_official_metadata_endpoints,
        test_exact_cmr_response_rejects_other_identity,
        test_dmr_validation_reads_metadata_only,
        test_classification_is_fail_closed,
        test_refresh_validation_uses_new_decision_identity,
        test_refresh_output_must_stay_in_task1_tree,
    ]
    for test in tests:
        test()
    print(json.dumps({"passed": len(tests), "failed": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
