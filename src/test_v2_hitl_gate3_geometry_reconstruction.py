#!/usr/bin/env python3
"""Network-free tests for D0069 mapped-cell geometry reconstruction evidence."""

from __future__ import annotations

import json
import inspect
from pathlib import Path
import tempfile

import numpy as np

from run_v2_hitl_gate3_second_augmentation import (
    GEOMETRY_RECONSTRUCTION_FORMAT,
    GEOMETRY_RECONSTRUCTION_MAX_BYTES,
    _geometry_reconstruction_storage_preflight,
    _geometry_resume_validation_payload,
    _canonical_sha256,
    _enforce_credited_cache_at_use,
    _reconstruction_cache_valid,
    _write_geometry_reconstruction,
    run_geometry,
)


class _Grid:
    def __init__(self, size: int):
        self.size = size


def _artifact(root: Path) -> tuple[Path, dict]:
    path = root / "city" / "00001.npz"
    grids = {"TILE_A": _Grid(3), "TILE_B": _Grid(2)}
    combined = {
        "TILE_A": {
            "view": np.asarray([1.0, np.nan, 3.0], dtype=np.float32),
            "view_azimuth": np.asarray([10.0, np.nan, 30.0], dtype=np.float32),
            "solar_azimuth": np.asarray([40.0, np.nan, 70.0], dtype=np.float32),
        },
        "TILE_B": {
            "view": np.asarray([np.nan, 5.0], dtype=np.float32),
            "view_azimuth": np.asarray([np.nan, 50.0], dtype=np.float32),
            "solar_azimuth": np.asarray([np.nan, 80.0], dtype=np.float32),
        },
    }
    record = _write_geometry_reconstruction(
        path,
        city="city",
        window_id="window",
        orbit=1,
        target_grid_sha256="a" * 64,
        grids=grids,
        combined=combined,
    )
    return path, record


def test_sparse_reconstruction_inventory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path, record = _artifact(Path(directory))
        assert record["format_version"] == GEOMETRY_RECONSTRUCTION_FORMAT
        assert record["n_domain_pixels"] == 5
        assert record["n_valid_target_cells"] == 3
        assert _reconstruction_cache_valid({"reconstruction_artifact": record})
        with np.load(path, allow_pickle=False) as evidence:
            assert evidence["valid_target_index"].tolist() == [0, 2, 4]
            assert evidence["view_zenith_abs_deg"].tolist() == [1.0, 3.0, 5.0]


def test_missing_reconstruction_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path, record = _artifact(Path(directory))
        path.unlink()
        assert not _reconstruction_cache_valid({"reconstruction_artifact": record})


def test_tampered_reconstruction_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path, record = _artifact(Path(directory))
        with path.open("ab") as handle:
            handle.write(b"tamper")
        assert not _reconstruction_cache_valid({"reconstruction_artifact": record})


def test_live_storage_preflight_includes_reserve_and_overhead() -> None:
    class _Usage:
        free = 10_000_000

    with tempfile.TemporaryDirectory() as directory:
        result = _geometry_reconstruction_storage_preflight(
            {"city": 10},
            ["city", "city"],
            storage_root=Path(directory),
            reserve_bytes=100,
            evidence_path=None,
            disk_usage=lambda _: _Usage(),
        )
        assert result["raw_array_worst_case_bytes"] == 320
        assert result["container_overhead_bytes"] == 2 * 1024**2
        assert result["required_free_bytes"] == result["conservative_new_data_bytes"] + 100


def test_live_storage_preflight_fails_when_free_space_changes() -> None:
    class _Usage:
        free = 1

    with tempfile.TemporaryDirectory() as directory:
        try:
            _geometry_reconstruction_storage_preflight(
                {"city": 10},
                ["city"],
                storage_root=Path(directory),
                reserve_bytes=100,
                evidence_path=None,
                disk_usage=lambda _: _Usage(),
            )
        except RuntimeError as exc:
            assert "live storage preflight failed" in str(exc)
        else:
            raise AssertionError("Insufficient live free space did not fail closed")


def test_artifact_cap_applies_to_arrays_while_overhead_stays_in_space_guard() -> None:
    class _Usage:
        free = 20 * 1024**3

    cells = GEOMETRY_RECONSTRUCTION_MAX_BYTES // 16
    with tempfile.TemporaryDirectory() as directory:
        result = _geometry_reconstruction_storage_preflight(
            {"city": cells},
            ["city"],
            storage_root=Path(directory),
            reserve_bytes=0,
            evidence_path=None,
            disk_usage=lambda _: _Usage(),
        )
        assert result["raw_array_worst_case_bytes"] == GEOMETRY_RECONSTRUCTION_MAX_BYTES
        assert result["conservative_new_data_bytes"] > GEOMETRY_RECONSTRUCTION_MAX_BYTES


def test_sealed_accessible_census_preflight_known_answer() -> None:
    class _Usage:
        free = 17 * 1024**3

    domain_cells = {
        "atlanta": 1_370_545,
        "minneapolis_st_paul": 571_534,
        "denver_aurora": 346_536,
        "phoenix": 588_636,
    }
    candidate_cities = (
        ["atlanta"] * 188
        + ["minneapolis_st_paul"] * 258
        + ["denver_aurora"] * 220
        + ["phoenix"] * 68
    )
    with tempfile.TemporaryDirectory() as directory:
        result = _geometry_reconstruction_storage_preflight(
            domain_cells,
            candidate_cities,
            storage_root=Path(directory),
            evidence_path=None,
            disk_usage=lambda _: _Usage(),
        )
        assert result["candidate_passes"] == 734
        assert result["raw_array_worst_case_bytes"] == 8_342_134_400
        assert result["container_overhead_bytes"] == 769_654_784
        assert result["conservative_new_data_bytes"] == 9_111_789_184
        assert result["required_free_bytes"] == 14_480_498_304
        assert result["status"] == "PASS"


def test_resume_preflight_credits_only_validated_completed_census() -> None:
    class _Usage:
        free = 6 * 1024**3

    with tempfile.TemporaryDirectory() as directory:
        result = _geometry_reconstruction_storage_preflight(
            {"atlanta": 10, "denver_aurora": 20},
            ["atlanta", "denver_aurora"],
            completed_candidate_cities=["atlanta"],
            completed_validation_digests={"atlanta:00001": "a" * 64},
            storage_root=Path(directory),
            evidence_path=None,
            disk_usage=lambda _: _Usage(),
        )
        assert result["candidate_passes"] == 2
        assert result["completed_passes"] == 1
        assert result["remaining_passes"] == 1
        assert result["raw_array_worst_case_bytes"] == 480
        assert result["completed_raw_array_worst_case_bytes"] == 160
        assert result["remaining_raw_array_worst_case_bytes"] == 320
        assert result["completed_container_overhead_bytes"] == 1024**2
        assert result["remaining_container_overhead_bytes"] == 1024**2
        assert result["required_free_bytes"] == (
            result["remaining_conservative_new_data_bytes"]
            + result["explicit_reserve_bytes"]
        )
        assert result["credited_completed_item_ids"] == ["atlanta:00001"]


def test_resume_preflight_rejects_unvalidated_or_malformed_credit() -> None:
    class _Usage:
        free = 10 * 1024**3

    with tempfile.TemporaryDirectory() as directory:
        for completed, digests in (
            (["city"], {}),
            (["city"], {"city:00001": "bad"}),
            (["unknown"], {"unknown:00001": "a" * 64}),
        ):
            try:
                _geometry_reconstruction_storage_preflight(
                    {"city": 10},
                    ["city"],
                    completed_candidate_cities=completed,
                    completed_validation_digests=digests,
                    storage_root=Path(directory),
                    evidence_path=None,
                    disk_usage=lambda _: _Usage(),
                )
            except ValueError:
                pass
            else:
                raise AssertionError("Unvalidated resume storage credit was accepted")


def test_strengthened_reconstruction_cache_rejects_identity_and_path_tamper() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path, record = _artifact(root)
        document = {"reconstruction_artifact": record}
        expected = {
            "expected_city": "city",
            "expected_window_id": "window",
            "expected_orbit": 1,
            "expected_target_grid_sha256": "a" * 64,
            "expected_n_domain_pixels": 5,
            "expected_path": path,
        }
        assert _reconstruction_cache_valid(document, **expected)
        for key, value in (
            ("expected_city", "wrong"),
            ("expected_window_id", "wrong"),
            ("expected_orbit", 2),
            ("expected_target_grid_sha256", "b" * 64),
            ("expected_n_domain_pixels", 6),
            ("expected_path", root / "other.npz"),
        ):
            bad = dict(expected)
            bad[key] = value
            assert not _reconstruction_cache_valid(document, **bad)


def test_existing_zero_npz_is_not_reusable_without_exact_worker_cache() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "zero.npz"
        grids = {"TILE_A": _Grid(3)}
        record = _write_geometry_reconstruction(
            path,
            city="city",
            window_id="window",
            orbit=1,
            target_grid_sha256="a" * 64,
            grids=grids,
            combined=None,
        )
        assert _reconstruction_cache_valid({"reconstruction_artifact": record})
        # A bare valid zero artifact is deliberately not itself a resume credit;
        # credit requires the exact checkpoint/evidence validation performed by
        # `_validated_geometry_resume_credits`.
        result = _geometry_reconstruction_storage_preflight(
            {"city": 3},
            ["city"],
            completed_candidate_cities=[],
            completed_validation_digests={},
            storage_root=root,
            reserve_bytes=0,
            evidence_path=None,
            disk_usage=lambda _: type("Usage", (), {"free": 10_000_000})(),
        )
        assert result["completed_passes"] == 0
        assert result["remaining_passes"] == 1


def test_mutated_credited_cache_stops_before_unbudgeted_rewrite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        evidence = Path(directory) / "evidence.json"
        evidence.write_text("{}", encoding="utf-8")
        try:
            _enforce_credited_cache_at_use(
                "city:00001",
                "a" * 64,
                None,
                {"status": "complete"},
                evidence,
            )
        except RuntimeError as exc:
            assert "rerun preflight" in str(exc)
        else:
            raise AssertionError("Mutated credited cache was allowed to recompute")


def test_credited_cache_digest_change_stops_before_no_write_return() -> None:
    with tempfile.TemporaryDirectory() as directory:
        evidence = Path(directory) / "evidence.json"
        document = {
            "binding": {"city": "city", "orbit": 1},
            "summary": {"window_id": "window"},
            "reconstruction_artifact": {
                "path": str(Path(directory) / "reconstruction.npz"),
                "sha256": "b" * 64,
                "size_bytes": 1,
                "format_version": "v1",
                "target_grid_sha256": "c" * 64,
                "n_domain_pixels": 3,
                "n_valid_target_cells": 1,
            },
        }
        evidence.write_text(json.dumps(document), encoding="utf-8")
        try:
            _enforce_credited_cache_at_use(
                "city:00001",
                "a" * 64,
                {"status": "complete"},
                {"status": "complete", "binding_sha256": "d" * 64},
                evidence,
            )
        except RuntimeError as exc:
            assert "rerun preflight" in str(exc)
        else:
            raise AssertionError("Changed credited digest was allowed to return")


def test_credited_reconstruction_mutation_fails_at_use() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path, record = _artifact(root)
        evidence = root / "evidence.json"
        document = {
            "binding": {"city": "city", "orbit": 1},
            "summary": {"window_id": "window"},
            "reconstruction_artifact": record,
        }
        evidence.write_text(json.dumps(document), encoding="utf-8")
        cached = {"status": "complete", "binding_sha256": "d" * 64}
        sealed_digest = _canonical_sha256(
            _geometry_resume_validation_payload(
                "city:00001", cached, evidence, document
            )
        )
        with path.open("ab") as handle:
            handle.write(b"changed-after-preflight")
        try:
            _enforce_credited_cache_at_use(
                "city:00001",
                sealed_digest,
                {"status": "complete"},
                cached,
                evidence,
            )
        except RuntimeError as exc:
            assert "rerun preflight" in str(exc)
        else:
            raise AssertionError("Mutated credited NPZ was allowed to return")


def test_credited_worker_branch_precedes_zero_map_write_branch() -> None:
    source = inspect.getsource(run_geometry)
    credited_branch = source.index("if expected_completion_digest is not None:")
    zero_reuse_branch = source.index("reused = _no_overlap_reuse(")
    reconstruction_write = source.index("reconstruction = _write_geometry_reconstruction(")
    assert credited_branch < zero_reuse_branch < reconstruction_write


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print("PASS test_v2_hitl_gate3_geometry_reconstruction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
