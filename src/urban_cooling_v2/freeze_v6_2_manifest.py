#!/usr/bin/env python3
"""Create the D0 SHA-256 inventory for every inherited repository file.

The scan deliberately excludes Git internals and paths created by the v6.2 freeze
itself. Everything else present in the repository is treated as inherited, including
ignored raw data and historical outputs. Files are read as bytes only; no raster,
table, model, or thermal value is parsed or displayed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


FREEZE_PREFIXES = (
    ".git/",
    "docs/v2/v6_2/",
    "docs/v2/archive/pre_v6_2_20260830/",
    "outputs/v6_2/",
    "tests/fixtures/synthetic_demo/",
)

FREEZE_FILES = {
    "src/urban_cooling_v2/freeze_v6_2_manifest.py",
    "src/urban_cooling_v2/v6_2_output_boundary.py",
    "src/test_v6_2_output_boundary.py",
}


def is_freeze_artifact(relative: str) -> bool:
    normalized = relative.replace(os.sep, "/")
    return normalized in FREEZE_FILES or any(
        normalized.startswith(prefix) for prefix in FREEZE_PREFIXES
    )


def inherited_files(repository: Path) -> list[Path]:
    files: list[Path] = []
    for directory, directory_names, file_names in os.walk(repository):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(repository).as_posix()
        if relative_directory == ".git" or relative_directory.startswith(".git/"):
            directory_names[:] = []
            continue

        kept_directories: list[str] = []
        for name in directory_names:
            candidate = (directory_path / name).relative_to(repository).as_posix() + "/"
            if not is_freeze_artifact(candidate):
                kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in file_names:
            path = directory_path / name
            relative = path.relative_to(repository).as_posix()
            if not is_freeze_artifact(relative):
                files.append(path)
    return sorted(files, key=lambda item: item.relative_to(repository).as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def write_status(repository: Path, output: Path) -> None:
    status = git_output(repository, "status", "--porcelain=v1", "--untracked-files=all")
    inherited_lines: list[str] = []
    for line in status.splitlines():
        path_field = line[3:] if len(line) >= 4 else ""
        paths = [part.strip() for part in path_field.split(" -> ")]
        if paths and all(is_freeze_artifact(path) for path in paths):
            continue
        inherited_lines.append(line)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# Inherited working-state snapshot at the v6.2 freeze\n"
        "# This records the dirty state; it is not a commit. v6.2 freeze artifacts are excluded.\n"
        + ("\n".join(inherited_lines) + "\n" if inherited_lines else "CLEAN\n"),
        encoding="utf-8",
    )


def write_manifest(repository: Path, output: Path) -> tuple[int, int]:
    paths = inherited_files(repository)
    output.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write("# SHA-256 inventory of every inherited repository file\n")
        temporary.write("# Frozen: 2026-08-30T17:58:40+09:00\n")
        temporary.write("# Branch: v6.2\n")
        temporary.write(
            "# Inherited commit: e32ff06aad83f1c8fe87473bf5c95e9e12f155e2\n"
        )
        temporary.write("# Tag: v2-inherited-pre-v6.2\n")
        temporary.write(
            "# Scope: all files under the repository root present before the freeze, "
            "including ignored data and outputs; excludes .git and v6.2 freeze artifacts.\n"
        )
        temporary.write("# Format: sha256  bytes  relative_path\n")

        for index, path in enumerate(paths, start=1):
            relative = path.relative_to(repository).as_posix()
            size = path.stat().st_size
            total_bytes += size
            temporary.write(f"{sha256(path)}  {size}  {relative}\n")
            if index % 1000 == 0:
                print(
                    f"hashed {index}/{len(paths)} files "
                    f"({total_bytes / (1024 ** 3):.2f} GiB)",
                    flush=True,
                )

        temporary.write(f"# file_count: {len(paths)}\n")
        temporary.write(f"# total_bytes: {total_bytes}\n")

    temporary_path.replace(output)
    return len(paths), total_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/v2/v6_2/checksums.txt"),
    )
    parser.add_argument(
        "--status-output",
        type=Path,
        default=Path("docs/v2/v6_2/inherited_git_status.txt"),
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="refresh only the filtered inherited Git-status snapshot",
    )
    args = parser.parse_args()

    repository = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repository / args.output
    status_output = (
        args.status_output
        if args.status_output.is_absolute()
        else repository / args.status_output
    )

    if git_output(repository, "rev-parse", "--show-toplevel") != str(repository):
        raise SystemExit(f"--repo is not the Git repository root: {repository}")
    if git_output(repository, "branch", "--show-current") != "v6.2":
        raise SystemExit("refusing to freeze outside branch v6.2")
    if (
        git_output(repository, "rev-parse", "v2-inherited-pre-v6.2^{}")
        != "e32ff06aad83f1c8fe87473bf5c95e9e12f155e2"
    ):
        raise SystemExit("inherited tag does not resolve to the frozen commit")

    write_status(repository, status_output)
    if args.status_only:
        print(f"wrote {status_output.relative_to(repository)}", flush=True)
        return 0
    count, total_bytes = write_manifest(repository, output)
    print(
        f"wrote {output.relative_to(repository)}: {count} files, "
        f"{total_bytes / (1024 ** 3):.2f} GiB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
