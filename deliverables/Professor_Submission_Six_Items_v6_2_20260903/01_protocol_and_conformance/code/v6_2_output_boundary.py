#!/usr/bin/env python3
"""Fail closed when v6.2 scientific, sealed, retired, or synthetic roots mix."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOTS = {
    "scientific": Path("outputs/v6_2/scientific"),
    "sealed": Path("outputs/v6_2/sealed_coefficients"),
    "retired": Path("outputs/v6_2/retired"),
    "synthetic": Path("tests/fixtures/synthetic_demo"),
}

NONSCIENTIFIC_TOKENS = ("synthetic", "illustrative", "demo", "retired", "legacy")
SCIENTIFIC_RESULT_TOKENS = ("headline", "coefficient", "estimate", "theta", "effect")


def files_below(path: Path) -> list[Path]:
    return [item for item in path.rglob("*") if item.is_file()]


def guarded_output_path(repository: Path, role: str, relative_name: str) -> Path:
    """Return a role-safe path, refusing traversal or cross-class naming.

    Every new v6.2 writer is required to use this function before opening an output.
    """

    if role not in ROOTS:
        raise ValueError(f"unknown output role: {role}")
    root = (repository.resolve() / ROOTS[role]).resolve()
    candidate = (root / relative_name).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"output escapes frozen {role} root: {relative_name}")

    lowered = candidate.name.lower()
    if role in {"scientific", "sealed"} and any(
        token in lowered for token in NONSCIENTIFIC_TOKENS
    ):
        raise ValueError(f"non-scientific artifact cannot target {role} root")
    if role == "synthetic" and "synthetic_data" not in lowered:
        raise ValueError("synthetic output filename must contain SYNTHETIC_DATA")
    if role == "retired" and not any(
        token in lowered for token in ("retired", "legacy", "superseded")
    ):
        raise ValueError("retired output filename must carry a retired/legacy marker")
    return candidate


def validate(repository: Path) -> list[str]:
    errors: list[str] = []
    resolved: dict[str, Path] = {}

    for role, relative in ROOTS.items():
        path = repository / relative
        if not path.is_dir():
            errors.append(f"missing {role} root: {relative}")
            continue
        resolved[role] = path.resolve()

    if len(set(resolved.values())) != len(resolved):
        errors.append("output roots do not resolve to four distinct directories")

    for role, path in resolved.items():
        expected = (repository / ROOTS[role]).resolve()
        if path != expected:
            errors.append(f"{role} root resolves outside its frozen location")

    scientific = repository / ROOTS["scientific"]
    if scientific.is_dir():
        for path in files_below(scientific):
            if path.name == "README.md":
                continue
            lowered = path.name.lower()
            token = next((x for x in NONSCIENTIFIC_TOKENS if x in lowered), None)
            if token:
                errors.append(
                    f"non-scientific token {token!r} inside scientific root: "
                    f"{path.relative_to(repository)}"
                )

    synthetic = repository / ROOTS["synthetic"]
    if synthetic.is_dir():
        for path in files_below(synthetic):
            if path.name == "README.md":
                continue
            if "synthetic_data" not in path.name.lower():
                errors.append(
                    "synthetic fixture lacks SYNTHETIC_DATA filename marker: "
                    f"{path.relative_to(repository)}"
                )

    for role in ("retired", "synthetic"):
        path = repository / ROOTS[role]
        if not path.is_dir():
            continue
        for artifact in files_below(path):
            if artifact.name == "README.md":
                continue
            lowered = artifact.name.lower()
            token = next((x for x in SCIENTIFIC_RESULT_TOKENS if x in lowered), None)
            if token and role == "retired" and "retired" not in lowered:
                errors.append(
                    f"unmarked scientific-result token {token!r} in retired root: "
                    f"{artifact.relative_to(repository)}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repository = args.repo.resolve()
    errors = validate(repository)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: four distinct v6.2 output roots; no boundary violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
