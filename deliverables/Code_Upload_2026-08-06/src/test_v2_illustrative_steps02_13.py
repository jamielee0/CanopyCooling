"""Offline tests for the quarantined illustrative Steps 2--13 runner."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import socket
import tempfile
import unittest

from run_v2_illustrative_steps02_13 import (
    REQUIRED_IDS_BY_STEP,
    index_required_ids,
    offline_network_guard,
    reject_canonical_pass_claims,
    run_package,
)
from urban_cooling_v2.illustrative_steps02_03 import STATUS, status_contract


ROOT = Path(__file__).resolve().parents[1]


def _stub_writer(first_step: int, last_step: int):
    def write(output_root: Path, figure_root: Path, seed: int):
        output_root = Path(output_root)
        figure_root = Path(figure_root)
        created: dict[str, Path] = {}
        for step in range(first_step, last_step + 1):
            for artifact_id in REQUIRED_IDS_BY_STEP[step]:
                if artifact_id.startswith("F"):
                    path = figure_root / f"ILLUSTRATIVE_{artifact_id}_stub.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"synthetic test figure")
                else:
                    path = output_root / f"ILLUSTRATIVE_{artifact_id}_stub.csv"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(
                        "data_origin,scientific_gate_eligible,task1_gate\n"
                        "synthetic,false,STOP\n",
                        encoding="utf-8",
                    )
                created[artifact_id] = path
        return created

    return write


class IllustrativeSteps0213Tests(unittest.TestCase):
    def test_status_contract_is_exact_stop(self) -> None:
        self.assertEqual(
            status_contract(),
            {
                "status": STATUS,
                "scientific_gate_eligible": False,
                "task1_gate": "STOP",
                "task2_activated": False,
                "lst_opened": False,
                "thermal_opened": False,
                "holdout_status": "UNSELECTED",
                "record_2026_opened": False,
            },
        )

    def test_offline_guard_rejects_connection(self) -> None:
        with offline_network_guard():
            with self.assertRaisesRegex(RuntimeError, "network access is forbidden"):
                socket.create_connection(("example.invalid", 443))

    def test_rejects_canonical_pass_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "data"
            figures = base / "figures"
            output.mkdir()
            figures.mkdir()
            (output / "bad.json").write_text(
                json.dumps(
                    {
                        **status_contract(),
                        "canonical_status": "PASS",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "canonical PASS"):
                reject_canonical_pass_claims(output, figures)

    def test_full_wrapper_with_offline_stub_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "data"
            figures = base / "figures"
            result = run_package(
                output_root=output,
                figures_root=figures,
                repo_root=ROOT,
                seed=20260805,
                steps04_08_writer=_stub_writer(4, 8),
                steps09_13_writer=_stub_writer(9, 13),
            )
            self.assertEqual(result["status"], STATUS)
            self.assertFalse(result["scientific_gate_eligible"])
            self.assertEqual(result["task1_gate"], "STOP")
            self.assertFalse(result["task2_activated"])
            self.assertFalse(result["lst_opened"])
            self.assertFalse(result["thermal_opened"])
            self.assertEqual(result["holdout_status"], "UNSELECTED")
            self.assertFalse(result["record_2026_opened"])

            index = index_required_ids(output, figures)
            self.assertTrue(all(index.values()))
            for required in (
                "README.md",
                "run_manifest.json",
                "canonical_gate_status.json",
                "data_origin_dictionary.csv",
            ):
                self.assertGreater((output / required).stat().st_size, 0)
            self.assertTrue((output / "empirical_nonthermal").is_dir())
            self.assertTrue((output / "synthetic_downstream").is_dir())

            for table in output.rglob("*.csv"):
                with table.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertTrue(rows, f"empty CSV table: {table}")
                headers = set(rows[0])
                self.assertTrue(
                    headers.intersection({"data_origin", "origin_class"}),
                    f"missing standardized data_origin/origin_class column: {table}",
                )
                eligibility_columns = headers.intersection(
                    {"scientific_gate_eligible", "canonical_eligible"}
                )
                self.assertTrue(
                    eligibility_columns,
                    f"missing explicit eligibility column: {table}",
                )
                for column in eligibility_columns:
                    self.assertEqual(
                        {str(row[column]).strip().casefold() for row in rows},
                        {"false"},
                        f"eligibility is not uniformly false in {table}",
                    )

            facts = json.loads(
                (
                    output
                    / "empirical_nonthermal/step02/"
                    "EMPIRICAL_PARTIAL_step02_snapshot_facts.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(facts["catalogue_metadata_rows"], 2968)
            self.assertEqual(facts["daytime_catalogue_ceiling_passes"], 1055)
            self.assertEqual(facts["d0047_geometry_evaluated_at_user_skip"], 710)
            self.assertEqual(facts["d0047_geometry_unevaluated_at_user_skip"], 201)

            manifest = json.loads(
                (output / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["artifacts"])
            self.assertTrue(
                all(len(record["sha256"]) == 64 for record in manifest["artifacts"])
            )
            reject_canonical_pass_claims(output, figures)


if __name__ == "__main__":
    unittest.main()
