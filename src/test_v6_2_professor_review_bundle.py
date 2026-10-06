#!/usr/bin/env python3
"""Network-free tests for the v6.2 professor-review bundle builder."""

from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from build_v6_2_professor_review_bundle import (
    assert_safe_source,
    copy_and_record,
    sha256,
    write_checksums,
    write_file_index,
)


class ProfessorReviewBundleTests(unittest.TestCase):
    def test_copy_index_and_checksums_preserve_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            output = root / "bundle"
            source = repo / "src/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("print('v6.2')\n", encoding="utf-8")
            output.mkdir()
            records: list[dict[str, str | int]] = []

            copy_and_record(
                repo,
                output,
                "src/example.py",
                "05_code/src/example.py",
                "code",
                "CURRENT",
                "Synthetic code fixture.",
                records,
            )
            write_file_index(output, records)
            count = write_checksums(output)

            copied = output / "05_code/src/example.py"
            self.assertEqual(copied.read_bytes(), source.read_bytes())
            self.assertEqual(records[0]["sha256"], sha256(source))
            self.assertEqual(count, 2)
            with (output / "FILE_INDEX.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["source_path"], "src/example.py")

    def test_raw_and_sealed_paths_are_rejected(self):
        for path in (
            Path("data/raw/v2/file.tif"),
            Path("outputs/v6_2/sealed/result.csv"),
            Path("src/__pycache__/module.pyc"),
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    assert_safe_source(path)


if __name__ == "__main__":
    unittest.main()
