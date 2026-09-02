#!/usr/bin/env python3
"""Network-free tests for secure HLS download preparation."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_v6_2_d1c_hls_download import load_token, requested_assets, target_path
from store_earthdata_token import validate_token


FAKE_TOKEN = "eyJheader.payload.signature"


class HlsDownloadTests(unittest.TestCase):
    def test_token_validation_rejects_markdown_escaping(self):
        with self.assertRaises(ValueError):
            validate_token("eyJheader.pay\\_load.signature")

    def test_token_file_is_read_without_echoing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text(FAKE_TOKEN + "\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_token(path), FAKE_TOKEN)

    def test_fmask_is_the_default_qa_asset(self):
        row = {
            "fmask_url": "https://example.test/granule.Fmask.tif",
            "reflectance_urls": {
                "B04": "https://example.test/granule.B04.tif",
                "B8A": "https://example.test/granule.B8A.tif",
                "B11": "https://example.test/granule.B11.tif",
            },
        }
        self.assertEqual(requested_assets(row, "fmask"), [("Fmask", row["fmask_url"])])
        self.assertEqual(len(requested_assets(row, "all")), 4)

    def test_download_path_is_granule_scoped(self):
        row = {"sensor": "HLSS30.002", "optical_acquisition_id": "HLS.S30.test"}
        path = target_path(Path("/tmp/hls"), row, "https://example.test/HLS.S30.test.Fmask.tif")
        self.assertEqual(path.name, "HLS.S30.test.Fmask.tif")
        self.assertEqual(path.parent.name, "HLS.S30.test")


if __name__ == "__main__":
    unittest.main()
