#!/usr/bin/env python3
"""Network-free tests for official ECOSTRESS Step-2 metadata enrichment."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from urban_cooling_v2 import step02_enrich as enrich


def test_l2t_json_parser_handles_nested_official_fields() -> None:
    sidecar = {
        "StandardMetadata": {
            "LocalGranuleID": {
                "Value": "ECOv002_L2T_LSTE_28527_009_13TDE_20230718T081442_0710_01"
            },
            "OrbitNumber": {"value": "28527"},
            "SceneID": {"Values": ["009"]},
        },
        "ProductMetadata": {
            "FieldOfViewObstruction": {"Value": "No"},
            "AutomaticQualityFlag": {"Value": "Good"},
            "NumberOfBands": {"Value": "5"},
            "QAPercentCloudCover": {"Value": "37.5%"},
        },
    }
    parsed = enrich.parse_l2t_json(sidecar, source_name="sidecar.json")
    assert parsed.key == enrich.SceneKey(28527, 9)
    assert parsed.field_of_view_obstruction is False
    assert parsed.automatic_quality_flag == "good"
    assert parsed.number_of_bands == 5
    assert np.isclose(parsed.qa_percent_cloud_cover, 37.5)
    assert parsed.warnings == ()

    # The parser also supports a local sidecar file and filename fallback when
    # orbit/scene fields are not repeated inside JSON.
    with tempfile.TemporaryDirectory(prefix="l2t-json-") as temporary:
        path = Path(temporary) / (
            "ECOv003_L2T_LSTE_30001_012_12SVC_20240710T200000_0001_01.json"
        )
        path.write_text(
            '{"FieldOfViewObstruction":"Yes","AutomaticQualityFlag":"0",'
            '"NumberOfBands":3,"QAPercentCloudCover":72}',
            encoding="utf-8",
        )
        from_path = enrich.parse_l2t_json(path)
    assert from_path.key == enrich.SceneKey(30001, 12)
    assert from_path.field_of_view_obstruction is True
    assert from_path.automatic_quality_flag == "best"
    assert enrich.retrieval_band_mode(from_path.number_of_bands) == "reduced"


def test_l1b_geo_dmrpp_parser_is_namespace_and_shape_robust() -> None:
    dmrpp = b"""<?xml version="1.0"?>
    <Dataset xmlns="http://xml.opendap.org/ns/DAP/4.0#"
             xmlns:dmrpp="http://xml.opendap.org/dmrpp/1.0.0#">
      <Attribute name="OrbitNumber" type="Int32"><Value>28527</Value></Attribute>
      <Attribute name="SceneNumber" type="Int16"><Value value="009"/></Attribute>
      <Group name="Metadata">
        <Attribute name="GeolocationAccuracyQA" type="String">
          <Value value="Best"/>
        </Attribute>
      </Group>
    </Dataset>"""
    parsed = enrich.parse_l1b_geo_xml(dmrpp, source_name="not-a-product-name.dmrpp")
    assert parsed.key == enrich.SceneKey(28527, 9)
    assert parsed.geolocation_quality == "best"
    assert parsed.raw_geolocation_accuracy_qa == "Best"

    official_compact_shape = b"""<Dataset xmlns:dmrpp="http://xml.opendap.org/dmrpp/1.0.0#">
      <Group name="L1GEOMetadata">
        <String name="GeolocationAccuracyQA">
          <dmrpp:compact>R29vZA==</dmrpp:compact>
        </String>
      </Group>
    </Dataset>"""
    compact = enrich.parse_l1b_geo_xml(
        official_compact_shape,
        source_name="ECOv002_L1B_GEO_28527_009_20230718T081442_0710_01.h5.dmrpp",
    )
    assert compact.geolocation_quality == "good"
    assert compact.raw_geolocation_accuracy_qa == "Good"

    direct_element = """<root>
      <GeolocationAccuracyQA value="2"/>
      <OrbitNumber>28528</OrbitNumber><SceneID>10</SceneID>
    </root>"""
    suspect = enrich.parse_l1b_geo_xml(direct_element)
    assert suspect.key == enrich.SceneKey(28528, 10)
    assert suspect.geolocation_quality == "suspect"


def test_jpl_geolocation_flag_table_prefers_latest_revision() -> None:
    flags = """
    ECOv002_L1B_GEO_28527_009_20230718T081442_0710_01.h5 GeolocationAccuracyQA="Good"
    ECOv002_L1B_GEO_28527_009_20230718T081442_0711_02.h5 GeolocationAccuracyQA="Best"
    ECOv002_L1B_GEO_28528_010_20230719T081442_0710_01.h5 GeolocationAccuracyQA="Poor"
    """
    parsed = enrich.parse_geolocation_flag_table(flags)
    assert len(parsed) == 2
    assert parsed[0].key == enrich.SceneKey(28527, 9)
    assert parsed[0].geolocation_quality == "best"
    assert parsed[0].source_name.endswith("_0711_02.h5")
    assert parsed[1].geolocation_quality == "poor"


def test_official_obstruction_list_parser() -> None:
    text = """# published obstruction scenes
    orbit scene
    28527 009
    orbit=28528 scene=10
    ORB=28528 SCN=012 t1=2023-07-18T08:14:42 FOV_OBST=YES
    ECOv002_L1B_GEO_28529_011_20230718T081442_0710_01.h5
    28527,009  # duplicate
    this line is not data
    """
    result = enrich.parse_obstruction_list(text, strict=False)
    assert result.entries == (
        enrich.SceneKey(28527, 9),
        enrich.SceneKey(28528, 10),
        enrich.SceneKey(28528, 12),
        enrich.SceneKey(28529, 11),
    )
    assert result.unparsed_lines == ((8, "    this line is not data"),)
    try:
        enrich.parse_obstruction_list(text, strict=True)
    except enrich.MetadataParseError:
        pass
    else:
        raise AssertionError("strict parser should reject unexplained records")


def _l2t(
    orbit: int,
    scene: int,
    tile: str,
    *,
    obstruction: bool | None,
    quality: str = "best",
    bands: int | None = 5,
    cloud: float | None = 20,
) -> enrich.L2TGranuleMetadata:
    granule_id = f"ECOv003_L2T_LSTE_{orbit:05d}_{scene:03d}_{tile}_20240710T200000"
    return enrich.L2TGranuleMetadata(
        source_name=f"{granule_id}.json",
        granule_id=granule_id,
        key=enrich.SceneKey(orbit, scene),
        field_of_view_obstruction=obstruction,
        automatic_quality_flag=quality,
        number_of_bands=bands,
        qa_percent_cloud_cover=cloud,
    )


def _geo(orbit: int, scene: int, quality: str) -> enrich.GeoAccuracyMetadata:
    return enrich.GeoAccuracyMetadata(
        source_name=f"ECOv003_L1B_GEO_{orbit:05d}_{scene:03d}.dmrpp",
        key=enrich.SceneKey(orbit, scene),
        geolocation_quality=quality,
        raw_geolocation_accuracy_qa=quality,
    )


def test_conservative_scene_combination_and_catalogue_join() -> None:
    l2t = [
        _l2t(30001, 1, "12SVC", obstruction=False, cloud=20),
        _l2t(30001, 1, "12SVD", obstruction=False, quality="good", cloud=35),
        _l2t(30002, 2, "12SVC", obstruction=None, bands=None, cloud=None),
        _l2t(30003, 3, "12SVC", obstruction=False, bands=3, cloud=10),
    ]
    geo = [_geo(30001, 1, "best"), _geo(30001, 1, "good"), _geo(30003, 3, "poor")]
    obstruction = enrich.ObstructionListResult((enrich.SceneKey(30003, 3),))
    scenes = enrich.combine_official_scene_metadata(l2t, geo, obstruction)
    by_key = scenes.set_index("scene_key")

    clear = by_key.loc["30001_001"]
    assert clear["n_l2t_tiles"] == 2
    assert clear["geolocation_quality"] == "good"  # worst matching GEO record
    assert bool(clear["geolocation_usable"])
    assert clear["obstruction_status"] == "clear"
    assert not bool(clear["obstruction_flag"])
    assert np.isclose(clear["qa_percent_cloud_cover_max"], 35)
    assert clear["retrieval_band_mode"] == "full"

    unknown = by_key.loc["30002_002"]
    assert unknown["geolocation_quality"] == "suspect"
    assert unknown["obstruction_status"] == "unknown_excluded"
    assert bool(unknown["obstruction_flag"])
    assert not bool(unknown["official_metadata_complete"])

    flagged = by_key.loc["30003_003"]
    assert bool(flagged["published_obstruction_flag"])
    assert bool(flagged["obstruction_flag"])
    assert flagged["retrieval_band_mode"] == "reduced"
    assert flagged["geolocation_quality"] == "poor"

    catalogue = pd.DataFrame(
        {
            "city": ["Phoenix", "Phoenix", "Phoenix"],
            "orbit": ["30001", "30003", "39999"],
            "granule_id": [
                "ECOv003_L2T_LSTE_30001_001_12SVC_20240710T200000",
                "ECOv003_L2T_LSTE_30003_003_12SVC_20240710T200000",
                "ECOv003_L2T_LSTE_39999_099_12SVC_20240710T200000",
            ],
        }
    )
    joined = enrich.join_official_enrichment(catalogue, scenes)
    assert joined.loc[joined["orbit"] == 30001, "granule_id"].iloc[0].endswith(
        "12SVC_20240710T200000"
    )
    assert "official_scene_granule_ids" in joined
    missing = joined.loc[joined["orbit"] == 39999].iloc[0]
    assert missing["geolocation_quality"] == "suspect"
    assert bool(missing["obstruction_flag"])
    assert missing["obstruction_status"] == "unknown_excluded"


def test_domain_array_summary_uses_clear_cloud_fill_codes_without_lst() -> None:
    view = np.array([[5.0, -12.0, 18.0], [9.0, 17.0, 50.0]])
    cloud = np.array([[0, 1, 255], [0, 7, 0]], dtype=np.uint8)
    domain = np.array([[True, True, True], [True, True, False]])
    summary = enrich.summarize_domain_screening_arrays(
        view,
        cloud,
        domain,
        near_nadir_threshold_deg=20,
        minimum_view_coverage=1.0,
    )
    assert summary["n_domain_pixels"] == 5
    assert summary["n_view_valid_pixels"] == 5
    assert summary["near_nadir"] is True
    assert summary["view_zenith_abs_p95_deg"] <= 20
    assert summary["n_clear_pixels"] == 2
    assert summary["n_cloud_pixels"] == 1
    assert summary["n_cloud_fill_pixels"] == 1
    assert summary["n_unexpected_cloud_code_pixels"] == 1
    assert np.isclose(summary["cloud_survival_fraction_of_domain"], 2 / 5)

    view[0, 0] = 25
    failed = enrich.summarize_domain_screening_arrays(view, cloud, domain)
    assert failed["near_nadir"] is False


def test_checkpoint_resume_verifies_file_evidence_and_rejects_secrets() -> None:
    with tempfile.TemporaryDirectory(prefix="enrich-checkpoint-") as temporary:
        root = Path(temporary)
        evidence = root / "scene.json"
        evidence.write_text("official metadata", encoding="utf-8")
        checkpoint = root / "checkpoint.json"
        items = enrich.record_completed_file(
            checkpoint, item_id="30001_001_l2t", local_path=evidence
        )
        assert enrich.pending_item_ids(
            ["30001_001_l2t", "30001_001_geo"], items
        ) == ["30001_001_geo"]
        loaded = enrich.load_checkpoint(checkpoint)
        assert loaded["30001_001_l2t"]["status"] == "complete"

        evidence.write_text("changed", encoding="utf-8")
        assert enrich.pending_item_ids(["30001_001_l2t"], loaded) == [
            "30001_001_l2t"
        ]
        try:
            enrich.write_checkpoint(
                checkpoint,
                {"bad": {"status": "complete", "authorization": "secret"}},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("checkpoint must reject credential-shaped fields")


def main() -> int:
    tests = [
        test_l2t_json_parser_handles_nested_official_fields,
        test_l1b_geo_dmrpp_parser_is_namespace_and_shape_robust,
        test_jpl_geolocation_flag_table_prefers_latest_revision,
        test_official_obstruction_list_parser,
        test_conservative_scene_combination_and_catalogue_join,
        test_domain_array_summary_uses_clear_cloud_fill_codes_without_lst,
        test_checkpoint_resume_verifies_file_evidence_and_rejects_secrets,
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
        print(f"\n{len(failures)} of {len(tests)} enrichment tests failed")
        return 1
    print(f"\nAll {len(tests)} enrichment tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
