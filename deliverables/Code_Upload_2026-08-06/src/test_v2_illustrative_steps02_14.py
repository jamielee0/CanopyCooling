"""Offline tests for the quarantined illustrative Steps 2--14 runner."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest

from run_v2_illustrative_steps02_14 import (
    DEFAULT_FIGURES_ROOT,
    DEFAULT_OUTPUT_ROOT,
    REQUIRED_IDS_BY_STEP,
    index_required_ids,
    run_package,
)
from urban_cooling_v2.illustrative_steps02_03 import STATUS


ROOT = Path(__file__).resolve().parents[1]


def _stub_base_writer(first_step: int, last_step: int):
    def write(output_root: Path, figure_root: Path, seed: int):
        created: dict[str, Path] = {}
        for step in range(first_step, last_step + 1):
            for artifact_id in REQUIRED_IDS_BY_STEP[step]:
                if artifact_id.startswith("F"):
                    path = Path(figure_root) / f"ILLUSTRATIVE_{artifact_id}_stub.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"synthetic test figure")
                else:
                    path = Path(output_root) / f"ILLUSTRATIVE_{artifact_id}_stub.csv"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(
                        "data_origin,scientific_gate_eligible,task1_gate\n"
                        "synthetic,false,STOP\n",
                        encoding="utf-8",
                    )
                created[artifact_id] = path
        return created

    return write


def _stub_step14_figures(output_root: Path, figure_root: Path, seed: int):
    del output_root, seed
    created: dict[str, Path] = {}
    for number in range(1, 7):
        artifact_id = f"F14.{number}"
        path = Path(figure_root) / f"ILLUSTRATIVE_{artifact_id}_paper_stub.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"illustrative synthetic paper figure")
        created[artifact_id] = path
    return created


def _stub_step14_documents(
    output_root: Path,
    figure_root: Path,
    seed: int,
    status_contract: dict[str, object],
):
    del figure_root, seed
    if status_contract["task1_gate"] != "STOP":
        raise AssertionError("stub received an unsafe status")
    output = Path(output_root)
    memo = output / "ILLUSTRATIVE_M14.1_go_adjust_stop_memo.md"
    confirmatory = output / "ILLUSTRATIVE_M14.2_confirmatory_report_NOT_RUN.md"
    package = output / "ILLUSTRATIVE_P14.1_public_package_inventory.csv"
    memo.write_text("# M14.1\n\nCanonical decision: STOP.\n", encoding="utf-8")
    confirmatory.write_text("# M14.2\n\nConfirmatory run: NOT RUN.\n", encoding="utf-8")
    package.write_text(
        "data_origin,canonical_eligible,relative_path\n"
        "illustrative_package,false,data_root/README.md\n",
        encoding="utf-8",
    )
    return {"M14.1": memo, "M14.2": confirmatory, "P14.1": package}


class IllustrativeSteps0214Tests(unittest.TestCase):
    def test_default_roots_are_quarantined(self) -> None:
        self.assertIn("illustrative_only", DEFAULT_OUTPUT_ROOT.parts)
        self.assertIn("illustrative_only", DEFAULT_FIGURES_ROOT.parts)
        self.assertEqual(DEFAULT_OUTPUT_ROOT.name, "steps02_14")
        self.assertEqual(DEFAULT_FIGURES_ROOT.name, "steps02_14")

    def test_step14_registry_is_exact(self) -> None:
        self.assertEqual(
            REQUIRED_IDS_BY_STEP[14],
            (
                "F14.1",
                "F14.2",
                "F14.3",
                "F14.4",
                "F14.5",
                "F14.6",
                "M14.1",
                "M14.2",
                "P14.1",
            ),
        )
        self.assertEqual(sum(map(len, REQUIRED_IDS_BY_STEP.values())), 102)

    def test_step14_writers_remain_offline(self) -> None:
        def network_writer(output_root: Path, figure_root: Path, seed: int):
            del output_root, figure_root, seed
            socket.create_connection(("example.invalid", 443))

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "network access is forbidden"):
                run_package(
                    output_root=base / "data",
                    figures_root=base / "figures",
                    repo_root=ROOT,
                    seed=20260805,
                    steps04_08_writer=_stub_base_writer(4, 8),
                    steps09_13_writer=_stub_base_writer(9, 13),
                    step14_figure_writer=network_writer,
                    step14_document_writer=_stub_step14_documents,
                )

    def test_full_wrapper_with_offline_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "data"
            figures = base / "figures"
            result = run_package(
                output_root=output,
                figures_root=figures,
                repo_root=ROOT,
                seed=20260805,
                steps04_08_writer=_stub_base_writer(4, 8),
                steps09_13_writer=_stub_base_writer(9, 13),
                step14_figure_writer=_stub_step14_figures,
                step14_document_writer=_stub_step14_documents,
            )
            self.assertEqual(result["status"], STATUS)
            self.assertFalse(result["scientific_gate_eligible"])
            self.assertEqual(result["task1_gate"], "STOP")
            self.assertFalse(result["task2_activated"])
            self.assertFalse(result["lst_opened"])
            self.assertFalse(result["thermal_opened"])
            self.assertEqual(result["holdout_status"], "UNSELECTED")
            self.assertFalse(result["record_2026_opened"])
            self.assertEqual(result["confirmatory_run_status"], "NOT_RUN")
            self.assertEqual(result["required_artifact_id_count"], 102)
            self.assertEqual(result["figure_count"], 72)
            self.assertTrue(
                (output / "ILLUSTRATIVE_public_package_source_inventory.csv").is_file()
            )
            self.assertTrue(
                (output / "ILLUSTRATIVE_public_package_rebuild_instructions.md").is_file()
            )

            index = index_required_ids(output, figures)
            self.assertEqual(len(index), 102)
            self.assertTrue(all(len(matches) == 1 for matches in index.values()))

            gate = json.loads(
                (output / "canonical_gate_status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                gate["canonical_step14_status"],
                "INCOMPLETE_CONFIRMATORY_NOT_RUN",
            )
            self.assertFalse(gate["canonical_completion_claimed"])
            self.assertEqual(gate["required_artifact_id_count"], 102)
            self.assertEqual(gate["step14_paper_figure_count"], 6)

            with (output / "data_origin_dictionary.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                origin_rows = list(csv.DictReader(handle))
            self.assertEqual(len(origin_rows), 102)
            self.assertEqual(len({row["artifact_id"] for row in origin_rows}), 102)
            self.assertEqual(
                {row["scientific_gate_eligible"] for row in origin_rows},
                {"false"},
            )
            self.assertEqual(
                next(row for row in origin_rows if row["artifact_id"] == "M14.2")[
                    "completeness"
                ],
                "confirmatory_not_run",
            )

            manifest_path = output / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest["artifacts"]:
                relative = Path(record["relative_path"])
                root = output if relative.parts[0] == "data_root" else figures
                path = root / Path(*relative.parts[1:])
                self.assertEqual(path.stat().st_size, record["size_bytes"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    record["sha256"],
                )


if __name__ == "__main__":
    unittest.main()
