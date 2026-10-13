#!/usr/bin/env python3
"""Known-answer tests for the v6.2 output boundary."""

from __future__ import annotations

from pathlib import Path
import tempfile

from urban_cooling_v2.v6_2_output_boundary import ROOTS, guarded_output_path, validate


def make_roots(repository: Path) -> None:
    for relative in ROOTS.values():
        (repository / relative).mkdir(parents=True, exist_ok=True)


def test_clean_roots_pass() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        make_roots(repository)
        assert validate(repository) == []


def test_synthetic_in_scientific_fails() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        make_roots(repository)
        (repository / ROOTS["scientific"] / "SYNTHETIC_DATA_result.csv").write_text(
            "x\n", encoding="utf-8"
        )
        errors = validate(repository)
        assert any("inside scientific root" in error for error in errors)


def test_unmarked_synthetic_fixture_fails() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        make_roots(repository)
        (repository / ROOTS["synthetic"] / "example.csv").write_text(
            "x\n", encoding="utf-8"
        )
        errors = validate(repository)
        assert any("lacks SYNTHETIC_DATA" in error for error in errors)


def test_guard_refuses_cross_class_and_traversal() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        make_roots(repository)
        assert guarded_output_path(
            repository, "synthetic", "SYNTHETIC_DATA_known_answer.csv"
        ).parent == (repository / ROOTS["synthetic"]).resolve()
        for role, name in (
            ("scientific", "ILLUSTRATIVE_result.csv"),
            ("sealed", "SYNTHETIC_DATA_coefficients.csv"),
            ("synthetic", "unmarked.csv"),
            ("retired", "unmarked.csv"),
            ("scientific", "../../escape.csv"),
        ):
            try:
                guarded_output_path(repository, role, name)
            except ValueError:
                pass
            else:
                raise AssertionError(f"guard accepted {role=} {name=}")


def main() -> int:
    tests = (
        test_clean_roots_pass,
        test_synthetic_in_scientific_fails,
        test_unmarked_synthetic_fixture_fails,
        test_guard_refuses_cross_class_and_traversal,
    )
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
