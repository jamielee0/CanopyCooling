#!/usr/bin/env python3
"""Network-free tests for the ECOSTRESS Step-2 enrichment fetch adapter."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pandas as pd

from urban_cooling_v2 import step02_enrich_fetch as fetch


OFFICIAL_ROOT = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected"
L2T_ID = "ECOv002_L2T_LSTE_28527_009_13TDE_20230718T081442_0710_01"
OTHER_L2T_ID = "ECOv002_L2T_LSTE_28528_010_13TDE_20230719T081442_0710_01"


def _url(product: str, suffix: str, collection: str = "ECO_L2T_LSTE.002") -> str:
    return f"{OFFICIAL_ROOT}/{collection}/{product}/{product}{suffix}"


class FakeGranule:
    def __init__(self, related_urls: list[str], data_links: list[str] | None = None):
        self.umm = {"RelatedUrls": [{"URL": value} for value in related_urls]}
        self._data_links = list(data_links or [])

    def data_links(self) -> list[str]:
        return list(self._data_links)


def test_extracts_only_safe_allow_list_assets() -> None:
    json_url = _url(L2T_ID, ".json")
    view_url = _url(L2T_ID, "_view_zenith.tif")
    cloud_url = _url(L2T_ID, "_cloud.tif")
    lst_url = _url(L2T_ID, "_LST.tif")
    signed = f"{cloud_url}?access_token=do-not-store"
    untrusted = cloud_url.replace("nasa.gov", "example.test")
    granule = FakeGranule(
        [json_url, view_url, lst_url, signed, untrusted],
        [cloud_url, cloud_url],
    )

    assets = fetch.extract_related_assets([granule])
    assert [asset.asset_type for asset in assets] == [
        fetch.L2T_JSON,
        fetch.VIEW_ZENITH_COG,
        fetch.CLOUD_COG,
    ]
    assert {asset.source_url for asset in assets} == {json_url, view_url, cloud_url}
    assert all("LST.tif" not in asset.file_name for asset in assets)
    assert json_url not in repr(assets[0])
    assert "do-not-store" not in repr(assets)

    # Plain CMR-style mappings are supported in addition to earthaccess objects.
    mapped = fetch.extract_related_assets(
        {"umm": {"RelatedUrls": [{"URL": json_url}]}, "data_links": [view_url]}
    )
    assert {asset.asset_type for asset in mapped} == {
        fetch.L2T_JSON,
        fetch.VIEW_ZENITH_COG,
    }


def _geo_url(build: str, revision: str, stamp: str = "20230718T081442") -> str:
    product = f"ECOv002_L1B_GEO_28527_009_{stamp}_{build}_{revision}"
    return _url(product, ".h5.dmrpp", collection="ECO_L1B_GEO.002")


def test_l1b_geo_matching_prefers_latest_build_then_revision() -> None:
    candidates = fetch.extract_related_assets(
        [
            FakeGranule([_geo_url("0710", "09")]),
            FakeGranule([_geo_url("0711", "01")]),
            FakeGranule([_geo_url("0711", "02")]),
            # A newer timestamp must not outrank a newer build/revision.
            FakeGranule([_geo_url("0710", "10", "20230719T081442")]),
        ]
    )
    selected = fetch.select_latest_l1b_geo(candidates)
    assert set(selected) == {(28527, 9)}
    assert selected[(28527, 9)].build == 711
    assert selected[(28527, 9)].revision == 2
    assert selected[(28527, 9)].file_name.endswith("_0711_02.h5.dmrpp")

    # Current CMR records can list only the HDF5 URL; NASA's official workflow
    # derives the available DMR++ endpoint by appending `.dmrpp`.
    h5_only = _geo_url("0712", "03").removesuffix(".dmrpp")
    derived = fetch.extract_related_assets([FakeGranule([h5_only])])
    assert len(derived) == 1
    assert derived[0].asset_type == fetch.L1B_GEO_DMRPP
    assert derived[0].file_name.endswith(".h5.dmrpp")
    assert derived[0].source_url.endswith(".h5.dmrpp")


def test_manifest_is_target_scoped_and_exposes_missing_assets() -> None:
    l2t = FakeGranule(
        [
            _url(L2T_ID, ".json"),
            _url(L2T_ID, "_view_zenith.tif"),
            _url(L2T_ID, "_cloud.tif"),
            _url(OTHER_L2T_ID, ".json"),
        ]
    )
    geo = FakeGranule(
        [
            _geo_url("0710", "01"),
            _geo_url("0712", "03"),
        ]
    )
    targets = pd.DataFrame(
        [
            {
                "city": "Phoenix",
                "granule_id": L2T_ID,
                "orbit": "28527",
                "scene": "009",
            },
            {
                "city": "Miami",
                "granule_id": OTHER_L2T_ID,
                "orbit": 28528,
                "scene": 10,
            },
        ]
    )
    with tempfile.TemporaryDirectory(prefix="target-manifest-") as temporary:
        destination = Path(temporary) / "manifest.csv"
        manifest = fetch.create_target_manifest(
            targets,
            l2t_results=[l2t],
            l1b_geo_results=[geo],
            output_csv=destination,
        )
        assert destination.is_file()

    assert len(manifest) == 8
    assert set(manifest["city"]) == {"Phoenix", "Miami"}
    phoenix = manifest.loc[manifest["city"] == "Phoenix"].set_index("asset_type")
    assert (phoenix["status"] == "available").all()
    assert phoenix.loc[fetch.L1B_GEO_DMRPP, "selected_build"] == 712
    assert phoenix.loc[fetch.L1B_GEO_DMRPP, "selected_revision"] == 3

    miami = manifest.loc[manifest["city"] == "Miami"].set_index("asset_type")
    assert miami.loc[fetch.L2T_JSON, "status"] == "available"
    assert miami.loc[fetch.VIEW_ZENITH_COG, "status"] == "missing"
    assert miami.loc[fetch.CLOUD_COG, "status"] == "missing"
    assert miami.loc[fetch.L1B_GEO_DMRPP, "status"] == "missing"
    assert miami.loc[fetch.CLOUD_COG, "source_url"] is None
    assert manifest.groupby(["city", "granule_id"]).size().eq(4).all()


class FakeResponse:
    def __init__(self, payload: bytes, *, status_code: int, headers: dict[str, str]):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers
        self.closed = False

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.payload), chunk_size):
            yield self.payload[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class ResumeSession:
    def __init__(self, payload: bytes, offset: int):
        self.payload = payload
        self.offset = offset
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        # The fake observes the URL to validate the injected-session contract;
        # production code never prints or persists this value in a checkpoint.
        self.calls.append({"url": url, **kwargs})
        assert kwargs["headers"] == {"Range": f"bytes={self.offset}-"}
        remaining = self.payload[self.offset :]
        return FakeResponse(
            remaining,
            status_code=206,
            headers={
                "Content-Length": str(len(remaining)),
                "Content-Range": f"bytes {self.offset}-{len(self.payload) - 1}/{len(self.payload)}",
            },
        )


class NoCallSession:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("network should not be called")


class StaticSession:
    def __init__(self, payload_by_url: dict[str, bytes]):
        self.payload_by_url = payload_by_url

    def get(self, url: str, **kwargs):
        payload = self.payload_by_url[url]
        return FakeResponse(
            payload,
            status_code=200,
            headers={"Content-Length": str(len(payload))},
        )


def _available_json_record() -> dict:
    source = _url(L2T_ID, ".json")
    return {
        "item_id": "l2t-json-test-item",
        "asset_type": fetch.L2T_JSON,
        "status": "available",
        "file_name": f"{L2T_ID}.json",
        "source_url": source,
    }


def test_authenticated_download_resumes_hashes_and_reuses_checkpoint() -> None:
    payload = b'{"FieldOfViewObstruction":"No","NumberOfBands":5}'
    offset = 17
    record = _available_json_record()
    with tempfile.TemporaryDirectory(prefix="enrich-download-") as temporary:
        root = Path(temporary)
        directory = root / fetch.L2T_JSON
        directory.mkdir(parents=True)
        partial = directory / f"{record['file_name']}.part"
        partial.write_bytes(payload[:offset])
        checkpoint = root / "checkpoint.json"
        session = ResumeSession(payload, offset)

        result = fetch.download_manifest_asset(
            record,
            destination_root=root,
            checkpoint_path=checkpoint,
            session=session,
            chunk_size=7,
            max_bytes=1024,
        )
        assert result.local_path.read_bytes() == payload
        assert result.resumed is True
        assert result.cached is False
        assert result.size_bytes == len(payload)
        assert result.sha256 == hashlib.sha256(payload).hexdigest()
        assert len(session.calls) == 1

        checkpoint_text = checkpoint.read_text(encoding="utf-8")
        checkpoint_json = json.loads(checkpoint_text)
        assert "source_url" not in checkpoint_text
        assert "https://" not in checkpoint_text
        assert checkpoint_json["items"][record["item_id"]]["status"] == "complete"

        no_call = NoCallSession()
        cached = fetch.download_manifest_asset(
            record,
            destination_root=root,
            checkpoint_path=checkpoint,
            session=no_call,
        )
        assert cached.cached is True
        assert cached.sha256 == result.sha256
        assert no_call.calls == 0


def test_lst_cannot_reach_the_network_boundary() -> None:
    record = _available_json_record()
    record.update(
        {
            "asset_type": fetch.CLOUD_COG,
            "file_name": f"{L2T_ID}_LST.tif",
            "source_url": _url(L2T_ID, "_LST.tif"),
        }
    )
    session = NoCallSession()
    with tempfile.TemporaryDirectory(prefix="reject-lst-") as temporary:
        try:
            fetch.download_manifest_asset(
                record,
                destination_root=temporary,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                session=session,
            )
        except fetch.AssetManifestError:
            pass
        else:
            raise AssertionError("LST must be rejected before the session is called")
    assert session.calls == 0


def test_concurrent_downloader_uses_race_free_item_checkpoints() -> None:
    first = _available_json_record()
    second_url = _url(OTHER_L2T_ID, ".json")
    second = {
        "item_id": "l2t-json-second-item",
        "asset_type": fetch.L2T_JSON,
        "status": "available",
        "file_name": f"{OTHER_L2T_ID}.json",
        "source_url": second_url,
    }
    payloads = {
        first["source_url"]: b'{"NumberOfBands":5}',
        second_url: b'{"NumberOfBands":3}',
    }
    with tempfile.TemporaryDirectory(prefix="concurrent-download-") as temporary:
        root = Path(temporary)
        manifest = pd.DataFrame([first, second])
        results = fetch.download_target_manifest_concurrent(
            manifest,
            destination_root=root,
            checkpoint_path=root / "checkpoint.json",
            session_factory=lambda: StaticSession(payloads),
            max_workers=2,
            checkpoint_batch_size=2,
        )
        assert len(results) == 2
        assert all(result.local_path.is_file() for result in results)
        checkpoint_text = (root / "checkpoint.json").read_text(encoding="utf-8")
        assert "source_url" not in checkpoint_text and "https://" not in checkpoint_text


def test_target_orbit_scene_mismatch_is_rejected() -> None:
    bad = [{"city": "Phoenix", "granule_id": L2T_ID, "orbit": 99999, "scene": 9}]
    try:
        fetch.create_target_manifest(bad, l2t_results=[], l1b_geo_results=[])
    except fetch.AssetManifestError:
        pass
    else:
        raise AssertionError("target identity mismatch must fail closed")


def main() -> int:
    tests = [
        test_extracts_only_safe_allow_list_assets,
        test_l1b_geo_matching_prefers_latest_build_then_revision,
        test_manifest_is_target_scoped_and_exposes_missing_assets,
        test_authenticated_download_resumes_hashes_and_reuses_checkpoint,
        test_lst_cannot_reach_the_network_boundary,
        test_concurrent_downloader_uses_race_free_item_checkpoints,
        test_target_orbit_scene_mismatch_is_rejected,
    ]
    failures: list[tuple[str, Exception]] = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover - direct-run reporting
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    if failures:
        print(f"\n{len(failures)} of {len(tests)} enrichment-fetch tests failed")
        return 1
    print(f"\nAll {len(tests)} enrichment-fetch tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
