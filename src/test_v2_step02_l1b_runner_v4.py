#!/usr/bin/env python3
"""Network-free regression tests for the D0035 v4 L1B GEO runner."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from pyproj import CRS
from scipy.spatial import cKDTree

import run_v2_step02_l1b_geometry as runner
from urban_cooling_v2.step02_enrich import write_checkpoint
from urban_cooling_v2.step02_l1b_geometry import TargetGrid, parse_dmrpp_chunks, sha256_file


class _Response:
    def __init__(
        self,
        status_code: int,
        content: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = dict(headers or {})
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: object) -> _Response:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        if not self.responses:
            raise AssertionError("Unexpected extra HTTP request")
        return self.responses.pop(0)


class LocatorThreadSafetyTests(unittest.TestCase):
    def test_cached_locator_reads_are_serialized(self) -> None:
        counter_lock = threading.Lock()
        active = 0
        maximum_active = 0

        class Variable:
            def __getitem__(self, key: object) -> np.ndarray:
                return np.ones((2, 2), dtype=float)

        class Dataset:
            groups = {
                "Geolocation": type(
                    "Group",
                    (),
                    {"variables": {"latitude": Variable(), "longitude": Variable()}},
                )()
            }

            def __enter__(self) -> "Dataset":
                nonlocal active, maximum_active
                with counter_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep(0.02)
                return self

            def __exit__(self, *_: object) -> None:
                nonlocal active
                with counter_lock:
                    active -= 1

        with mock.patch.object(runner.netCDF4, "Dataset", return_value=Dataset()):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(
                    executor.map(runner._read_locator, [Path("fake.nc4")] * 4)
                )

        self.assertEqual(maximum_active, 1)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result[0].shape == (2, 2) for result in results))


def _partial(
    start: int,
    end: int,
    payload: bytes,
    *,
    total: int = 100,
    validator: str = "version-1",
    encoding: str = "identity",
) -> _Response:
    headers = {
        "Content-Range": f"bytes {start}-{end}/{total}",
        "x-amz-version-id": validator,
        "Content-Encoding": encoding,
    }
    return _Response(206, payload, headers)


def _dmrpp(*, origin: str = "[0,0]", offset: str = "10") -> str:
    variables = []
    for kind, name, nbytes in (
        ("Float64", "latitude", "20"),
        ("Float64", "longitude", "20"),
        ("Float32", "view_zenith", "10"),
    ):
        variables.append(
            f"""
            <{kind} name="{name}">
              <Dim size="5632"/><Dim size="5400"/>
              <p:chunks compressionType="deflate" byteOrder="LE" fillValue="0">
                <p:chunkDimensionSizes>5632 5400</p:chunkDimensionSizes>
                <p:chunk offset="{offset}" nBytes="{nbytes}"
                         chunkPositionInArray="{origin}"/>
              </p:chunks>
            </{kind}>
            """
        )
    return (
        '<Dataset xmlns="http://xml.opendap.org/ns/DAP/4.0#" '
        'xmlns:p="http://xml.opendap.org/dap/dmrpp/1.0.0#">'
        '<Group name="Geolocation">'
        + "".join(variables)
        + "</Group></Dataset>"
    )


class RangeFetcherTests(unittest.TestCase):
    def test_accepts_exact_identity_206_and_requires_stable_validator(self) -> None:
        responses = [
            _partial(0, 2, b"abc"),
            _partial(3, 4, b"de"),
        ]
        session = _Session(responses)
        fetch = runner._RangeFetcher(session, "https://example.test/object.h5", "scene")

        self.assertEqual(fetch(0, 2), b"abc")
        self.assertEqual(fetch(3, 4), b"de")
        self.assertEqual(fetch.n_requests, 2)
        self.assertEqual(fetch.n_bytes, 5)
        self.assertEqual(fetch.object_size_bytes, 100)
        self.assertEqual(fetch.object_validator, "version:version-1")
        self.assertTrue(all(response.closed for response in responses))
        self.assertTrue(
            all(call["headers"].get("Accept-Encoding") == "identity" for call in session.calls)
        )

    def test_rejects_nonexact_partial_responses(self) -> None:
        cases = {
            "full_response": _Response(
                200,
                b"abc",
                {"Content-Range": "bytes 0-2/100", "x-amz-version-id": "v1"},
            ),
            "wrong_range": _Response(
                206,
                b"abc",
                {"Content-Range": "bytes 1-3/100", "x-amz-version-id": "v1"},
            ),
            "missing_range": _Response(
                206, b"abc", {"x-amz-version-id": "v1"}
            ),
            "encoded": _partial(0, 2, b"abc", encoding="gzip"),
            "short": _partial(0, 2, b"ab"),
            "missing_validator": _Response(
                206, b"abc", {"Content-Range": "bytes 0-2/100"}
            ),
        }
        for label, response in cases.items():
            with self.subTest(label=label):
                fetch = runner._RangeFetcher(
                    _Session([response]), "https://example.test/object.h5", label
                )
                with self.assertRaises(RuntimeError):
                    fetch(0, 2)
                self.assertEqual(fetch.n_requests, 0)
                self.assertEqual(fetch.n_bytes, 0)
                self.assertTrue(response.closed)

    def test_rejects_changed_validator_and_total_size(self) -> None:
        for label, second in (
            ("validator", _partial(3, 5, b"def", validator="version-2")),
            ("object_size", _partial(3, 5, b"def", total=101)),
        ):
            with self.subTest(label=label):
                session = _Session([_partial(0, 2, b"abc"), second])
                fetch = runner._RangeFetcher(
                    session, "https://example.test/object.h5", label
                )
                self.assertEqual(fetch(0, 2), b"abc")
                with self.assertRaises(RuntimeError):
                    fetch(3, 5)
                self.assertEqual(fetch.n_requests, 1)
                self.assertEqual(fetch.n_bytes, 3)

    def test_range_size_and_cumulative_byte_caps_fail_before_request(self) -> None:
        session = _Session([_partial(0, 2, b"abc")])
        refresh_calls = 0

        def refresh_session() -> _Session:
            nonlocal refresh_calls
            refresh_calls += 1
            return _Session([])

        fetch = runner._RangeFetcher(
            session,
            "https://example.test/object.h5",
            "scene",
            max_total_bytes=2,
            refresh_session=refresh_session,
        )
        with self.assertRaisesRegex(RuntimeError, "byte guard"):
            fetch(0, 2)
        self.assertEqual(session.calls, [])
        self.assertEqual(refresh_calls, 0)

        fetch = runner._RangeFetcher(
            _Session([]), "https://example.test/object.h5", "scene"
        )
        with self.assertRaisesRegex(RuntimeError, "Unsafe range size"):
            fetch(10, 9)
        with self.assertRaisesRegex(RuntimeError, "Unsafe range size"):
            fetch(0, 16 * 1024 * 1024)

    def test_403_refreshes_once_and_persists_for_later_ranges(self) -> None:
        denied = _Response(403, b"")
        stale = _Session([denied])
        fresh_responses = [
            _partial(0, 2, b"abc"),
            _partial(3, 4, b"de"),
        ]
        fresh = _Session(fresh_responses)
        refresh_calls = 0

        def refresh_session() -> _Session:
            nonlocal refresh_calls
            refresh_calls += 1
            return fresh

        fetch = runner._RangeFetcher(
            stale,
            "https://example.test/object.h5",
            "scene",
            refresh_session=refresh_session,
        )

        self.assertEqual(fetch(0, 2), b"abc")
        self.assertEqual(fetch(3, 4), b"de")
        self.assertEqual(refresh_calls, 1)
        self.assertEqual(fetch.session_refresh_count, 1)
        self.assertEqual(len(stale.calls), 1)
        self.assertEqual(len(fresh.calls), 2)
        self.assertEqual(
            stale.calls[0]["headers"]["Range"], fresh.calls[0]["headers"]["Range"]
        )
        self.assertEqual(stale.calls[0]["url"], fresh.calls[0]["url"])
        self.assertEqual(stale.calls[0]["timeout"], fresh.calls[0]["timeout"])
        self.assertTrue(denied.closed)
        self.assertTrue(all(response.closed for response in fresh_responses))

    def test_refreshed_session_can_be_reused_by_a_later_scene(self) -> None:
        local = threading.local()
        local.session = _Session([_Response(403, b"")])
        fresh = _Session(
            [
                _partial(0, 2, b"abc"),
                _partial(10, 12, b"xyz"),
            ]
        )
        factory_calls = 0

        def session_factory() -> _Session:
            nonlocal factory_calls
            factory_calls += 1
            local.session = fresh
            return local.session

        first = runner._RangeFetcher(
            local.session,
            "https://example.test/object.h5",
            "scene-1",
            refresh_session=session_factory,
        )
        self.assertEqual(first(0, 2), b"abc")

        second = runner._RangeFetcher(
            local.session,
            "https://example.test/object.h5",
            "scene-2",
            refresh_session=session_factory,
        )
        self.assertEqual(second(10, 12), b"xyz")
        self.assertEqual(factory_calls, 1)
        self.assertEqual(first.session_refresh_count, 1)
        self.assertEqual(second.session_refresh_count, 0)

    def test_second_403_after_refresh_fails_closed(self) -> None:
        stale_denied = _Response(403, b"")
        fresh_denied = _Response(403, b"")
        stale = _Session([stale_denied])
        fresh = _Session([fresh_denied])
        refresh_calls = 0

        def refresh_session() -> _Session:
            nonlocal refresh_calls
            refresh_calls += 1
            return fresh

        fetch = runner._RangeFetcher(
            stale,
            "https://example.test/object.h5",
            "scene",
            refresh_session=refresh_session,
        )
        with self.assertRaisesRegex(RuntimeError, "Range status 403"):
            fetch(0, 2)
        self.assertEqual(refresh_calls, 1)
        self.assertEqual(fetch.session_refresh_count, 1)
        self.assertEqual(fetch.n_requests, 0)
        self.assertEqual(fetch.n_bytes, 0)
        self.assertTrue(stale_denied.closed)
        self.assertTrue(fresh_denied.closed)

    def test_404_never_refreshes_or_reclassifies(self) -> None:
        missing = _Response(404, b"")
        session = _Session([missing])
        refresh_calls = 0

        def refresh_session() -> _Session:
            nonlocal refresh_calls
            refresh_calls += 1
            return _Session([])

        fetch = runner._RangeFetcher(
            session,
            "https://example.test/object.h5",
            "scene",
            refresh_session=refresh_session,
        )
        with self.assertRaisesRegex(RuntimeError, "Range status 404"):
            fetch(0, 2)
        self.assertEqual(refresh_calls, 0)
        self.assertEqual(fetch.session_refresh_count, 0)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(missing.closed)

    def test_refresh_does_not_relax_immutable_object_validation(self) -> None:
        stale = _Session(
            [
                _partial(0, 2, b"abc", validator="version-1"),
                _Response(403, b""),
            ]
        )
        fresh = _Session(
            [_partial(3, 5, b"def", validator="version-2")]
        )
        fetch = runner._RangeFetcher(
            stale,
            "https://example.test/object.h5",
            "scene",
            refresh_session=lambda: fresh,
        )

        self.assertEqual(fetch(0, 2), b"abc")
        with self.assertRaisesRegex(RuntimeError, "object changed"):
            fetch(3, 5)
        self.assertEqual(fetch.session_refresh_count, 1)
        self.assertEqual(fetch.n_requests, 1)
        self.assertEqual(fetch.n_bytes, 3)


class SessionRefreshEvidenceTests(unittest.TestCase):
    @staticmethod
    def _ordinary_d0048_scene_evidence() -> dict[str, object]:
        return {
            "boundary_verified": True,
            "full_resolution_boundary_verified": True,
            "locator_shape": list(runner.NO_OVERLAP_LOCATOR_SHAPE),
            "locator_expected_count": runner.NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
            "locator_valid_count": runner.NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
            "locator_stride": runner.LOCATOR_STRIDE,
            "locator_stride_minus_one_pixels": runner.LOCATOR_STRIDE - 1,
            "locator_influence_m": runner.LOCATOR_INFLUENCE_M,
            "locator_max_unsampled_path_pixels": (
                runner.NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS
            ),
            "maximum_adjacent_source_displacement_m": (
                runner.MAX_ADJACENT_SOURCE_DISPLACEMENT_M
            ),
            "locator_uncertainty_bound_m": runner.NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
            "boundary_guard_distance_m": runner.BOUNDARY_GUARD_DISTANCE_M,
            "seed_source_margin_pixels": runner.LOCATOR_MARGIN_PIXELS,
            "row_major_tie_breaking": True,
            "verified_no_overlap_zero_imputed": False,
            "missing_scene_zero_coverage_assigned": False,
            "missing_scene_substitution_used": False,
            "proof_mode": "locator_near_domain",
            "proof_status": "near_domain_full_resolution_verified",
            "proof_acceptance_status": "ordinary_near_domain_mapping",
            "geometry_observation_status": "mapped_near_domain_geometry",
            "seeded_chunk_coords": [[0, 0]],
            "seeded_chunk_count": 1,
            "mapped_target_cell_count": 1,
        }

    def test_pre_d0049_evidence_without_refresh_field_remains_valid(self) -> None:
        evidence = self._ordinary_d0048_scene_evidence()
        with mock.patch.object(runner, "IMPLEMENTATION_DECISION_ID", "D0048"):
            self.assertTrue(runner._scene_boundary_evidence_valid(evidence))

    def test_refresh_evidence_count_is_limited_to_zero_or_one(self) -> None:
        with mock.patch.object(runner, "IMPLEMENTATION_DECISION_ID", "D0048"):
            for count in (0, 1):
                with self.subTest(count=count):
                    evidence = self._ordinary_d0048_scene_evidence()
                    evidence["session_refresh_count"] = count
                    self.assertTrue(runner._scene_boundary_evidence_valid(evidence))
            evidence = self._ordinary_d0048_scene_evidence()
            evidence["session_refresh_count"] = 2
            self.assertFalse(runner._scene_boundary_evidence_valid(evidence))


class DmrppValidationTests(unittest.TestCase):
    def test_rejects_malformed_chunk_origins_and_offsets(self) -> None:
        cases = {
            "negative_origin": _dmrpp(origin="[-1,0]"),
            "unaligned_origin": _dmrpp(origin="[1,0]"),
            "wrong_origin_rank": _dmrpp(origin="[0,0,0]"),
            "negative_offset": _dmrpp(offset="-1"),
        }
        with tempfile.TemporaryDirectory(prefix="d0035-dmrpp-") as temporary:
            for label, document in cases.items():
                with self.subTest(label=label):
                    path = Path(temporary) / f"{label}.dmrpp"
                    path.write_text(document, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        parse_dmrpp_chunks(path)


class FailClosedArtifactTests(unittest.TestCase):
    def test_pre_geometry_stop_replaces_stale_pass_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d0035-stop-") as temporary:
            root = Path(temporary).resolve()
            output = root / "processed"
            raw = root / "raw"
            paths = {
                "ROOT": root,
                "OUTPUT_DIR": output,
                "RAW_ROOT": raw,
                "SCENE_MANIFEST": raw / "scene_manifest.csv",
                "ASSET_CHECKPOINT": raw / "asset_checkpoint.json",
                "GEOMETRY_CHECKPOINT": raw / "geometry_checkpoint.json",
                "PASS_EVIDENCE_DIR": raw / "pass_evidence",
                "GEOMETRY_SUMMARY": output / "geometry.csv",
                "CLOUD_CHECKPOINT": raw / "cloud_checkpoint.json",
                "CLOUD_SUMMARY": output / "cloud.csv",
                "GEOMETRY_VALIDATION_JSON": output / "geometry_validation.json",
                "GEOMETRY_VALIDATION_CSV": output / "geometry_validation.csv",
                "COMBINED_VALIDATION_JSON": output / "combined_validation.json",
                "COMBINED_VALIDATION_CSV": output / "combined_validation.csv",
                "RUN_RECORD": output / "run_record.json",
            }
            output.mkdir(parents=True)
            stale = {
                "canonical_status": "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD",
                "scientific_gate_eligible": True,
            }
            paths["GEOMETRY_VALIDATION_JSON"].write_text(
                json.dumps(stale), encoding="utf-8"
            )
            paths["COMBINED_VALIDATION_JSON"].write_text(
                json.dumps(stale), encoding="utf-8"
            )
            paths["GEOMETRY_VALIDATION_CSV"].write_text(
                "canonical_status\nPASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD\n",
                encoding="utf-8",
            )
            paths["COMBINED_VALIDATION_CSV"].write_text(
                "canonical_status\nPASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD\n",
                encoding="utf-8",
            )

            with mock.patch.multiple(runner, **paths):
                result = runner._record_pre_geometry_stop(
                    "synthetic_preflight", "SyntheticFailure"
                )

            self.assertEqual(result, 2)
            geometry = json.loads(paths["GEOMETRY_VALIDATION_JSON"].read_text())
            combined = json.loads(paths["COMBINED_VALIDATION_JSON"].read_text())
            run_record = json.loads(paths["RUN_RECORD"].read_text())
            self.assertEqual(geometry["canonical_status"], "STOP_D0035_INCOMPLETE_GEOMETRY")
            self.assertFalse(geometry["geometry_complete"])
            self.assertEqual(combined["canonical_status"], "STOP_D0035_INCOMPLETE_GEOMETRY")
            self.assertFalse(combined["scientific_gate_eligible"])
            self.assertEqual(
                run_record["combined_validation"]["canonical_status"],
                "STOP_D0035_INCOMPLETE_GEOMETRY",
            )
            self.assertNotIn(
                "PASS_D0035", paths["COMBINED_VALIDATION_CSV"].read_text(encoding="utf-8")
            )


class PassCacheBindingTests(unittest.TestCase):
    def test_streamed_pass_cache_is_reused_only_for_exact_current_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d0035-pass-cache-") as temporary:
            root = Path(temporary).resolve()
            evidence_root = root / "evidence"
            checkpoint_path = root / "geometry_checkpoint.json"
            city, orbit, scene, granule = "test-city", 1, 2, "GEO_TEST"
            acquisition = pd.Timestamp("2020-07-01T00:00:00Z")
            x = np.array([0.0, 70.0])
            y = np.array([0.0, 0.0])
            grid = TargetGrid(
                city=city,
                tile="00AAA",
                crs=CRS.from_epsg(32631),
                x=x,
                y=y,
                tree=cKDTree(np.column_stack((x, y))),
            )
            target_grids = {city: {grid.tile: grid}}
            candidates = pd.DataFrame(
                {
                    "city": [city],
                    "orbit": [orbit],
                    "acquisition_utc": [acquisition],
                    "quality_candidate_pre_cloud": [False],
                }
            )
            manifest = pd.DataFrame(
                {
                    "orbit": [orbit],
                    "scene": [scene],
                    "granule_id": [granule],
                    "hdf_url": ["https://example.test/object.h5"],
                }
            )
            links = pd.DataFrame(
                {"city": [city], "orbit": [orbit], "scene": [scene]}
            )
            asset_binding = {
                "cmr_record_sha256": "a" * 64,
                "collection_concept_id": runner.COLLECTION_CONCEPT_ID,
                "dmrpp_sha256": "b" * 64,
                "locator_sha256": "c" * 64,
            }
            bindings = {granule: asset_binding}
            binding_payload = {
                "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                "decision_id": runner.DECISION_ID,
                "city": city,
                "orbit": orbit,
                "acquisition_utc": acquisition.isoformat(),
                "target_grid_sha256": runner._target_grid_fingerprint(target_grids[city]),
                "locator_stride": runner.LOCATOR_STRIDE,
                "source_margin_pixels": 64,
                "radius_m": runner.RADIUS_OF_INFLUENCE_M,
                "boundary_guard_m": runner.BOUNDARY_GUARD_DISTANCE_M,
                "max_selected_chunks": runner.MAX_SELECTED_CHUNKS_PER_SCENE,
                "max_range_bytes_per_scene": runner.MAX_RANGE_BYTES_PER_SCENE,
                "scene_bindings": [
                    {"orbit": orbit, "scene": scene, "granule_id": granule, **asset_binding}
                ],
            }
            binding_sha256 = hashlib.sha256(
                json.dumps(binding_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            summary = {
                "city": city,
                "orbit": orbit,
                "acquisition_utc": acquisition.isoformat(),
                "l1b_geometry_complete": True,
                "l1b_geometry_status": "geometry_pass",
                "quality_candidate_pre_cloud_l1b": True,
                "decision_id": runner.DECISION_ID,
                "cached_marker": "exact-binding",
            }
            evidence = {
                "status": "complete",
                "decision_id": runner.DECISION_ID,
                "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                "binding_sha256": binding_sha256,
                "binding": binding_payload,
                "boundary_verified": True,
                "city": city,
                "orbit": orbit,
                "scene_evidence": [{"boundary_verified": True}],
                "summary": summary,
            }
            evidence_path = evidence_root / city / f"{orbit:05d}.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            write_checkpoint(
                checkpoint_path,
                {
                    f"{city}:{orbit:05d}": {
                        "status": "complete",
                        "boundary_verified": True,
                        "evidence_path": str(evidence_path),
                        "evidence_sha256": sha256_file(evidence_path),
                        "binding_sha256": binding_sha256,
                        "range_bytes_transferred": 0,
                        "range_request_count": 0,
                    }
                },
            )
            factory_calls = 0

            def session_factory() -> object:
                nonlocal factory_calls
                factory_calls += 1
                return object()

            patches = {
                "EXPECTED_METADATA_CANDIDATES": 1,
                "GEOMETRY_CHECKPOINT": checkpoint_path,
                "PASS_EVIDENCE_DIR": evidence_root,
                "DMRPP_DIR": root / "dmrpp",
                "LOCATOR_DIR": root / "locator",
            }
            with mock.patch.multiple(runner, **patches):
                cached = runner._run_geometry_passes(
                    candidates,
                    manifest,
                    links,
                    target_grids,
                    bindings,
                    session_factory=session_factory,
                    max_workers=1,
                )
                self.assertEqual(cached.loc[0, "cached_marker"], "exact-binding")
                self.assertEqual(factory_calls, 0)

                changed = {granule: {**asset_binding, "locator_sha256": "d" * 64}}
                invalidated = runner._run_geometry_passes(
                    candidates,
                    manifest,
                    links,
                    target_grids,
                    changed,
                    session_factory=session_factory,
                    max_workers=1,
                )
            self.assertEqual(factory_calls, 1)
            self.assertEqual(invalidated.loc[0, "l1b_geometry_status"], "unresolved")
            self.assertFalse(bool(invalidated.loc[0, "l1b_geometry_complete"]))
            failure = runner.load_checkpoint(checkpoint_path)[f"{city}:{orbit:05d}"]
            self.assertEqual(failure["error_type"], "FileNotFoundError")
            self.assertIn("metadata asset missing", failure["error_message"])


if __name__ == "__main__":
    unittest.main()
