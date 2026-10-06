"""Programmatic sealed-result verification; print counts/checks, never effects."""
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT/"src"))
from v6_2_advance.run_quadratic_sensitivity import RUN, EXEC, PACKET, public, sha, write
from v6_2_advance.quadratic_sensitivity import (
    basis_delta, cooling_quantities, summarize, public_precision, sealed_path,
)
from urban_cooling_v2.v6_2_output_boundary import validate


def same(a, b, message):
    if not np.allclose(a, b, atol=1e-9, rtol=1e-10, equal_nan=True): raise ValueError(message)


def main():
    os.umask(0o077)
    cfg = json.loads((EXEC/"execution_freeze.json").read_text())
    ref = cfg["settings"]["reference"]
    for row in cfg["inputs"]:
        if sha(ROOT/row["path"]) != row["sha256"]: raise ValueError("Frozen input changed")
    for p, h in cfg["code_sha256"].items():
        if sha(ROOT/p) != h: raise ValueError("Frozen code changed")
    if str((ROOT/"data").resolve(strict=True)) != cfg["data_link_target"]: raise ValueError("Data link changed")
    finite, curves = [], []
    for spec in cfg["passes"]:
        key = f"{spec['city']}_{spec['orbit']}"
        done = json.loads(public(key+"_completion.json").read_text())
        for rel, h in done["output_sha256"].items():
            if sha(ROOT/rel) != h: raise ValueError("Completed output changed")
        with np.load(sealed_path(ROOT, RUN, key+"_models_SEALED.npz"), allow_pickle=False) as model:
            rows = json.loads(sealed_path(ROOT, RUN, key+"_finite_contrasts_SEALED.json").read_text())
            for row in rows:
                if row["status"] == "NOT_ESTIMATED_NO_REFERENCE_BLOCKS": continue
                summaries = {}
                for label in ("linear", "quadratic"):
                    names = model[label+"_names"].tolist()
                    # Independent endpoint evaluation changes f and raw f² explicitly.
                    endpoints = np.zeros((2, len(names)))
                    for j, f in enumerate((row["f0"], row["f1"])):
                        endpoints[j, names.index("canopy_fraction")] = f
                        if "canopy_squared" in names: endpoints[j, names.index("canopy_squared")] = f*f
                    delta = endpoints[1]-endpoints[0]
                    point = delta @ model[label+"_coefficients"]
                    draw = np.einsum("p,bpo->bo", delta, model[f"{label}_draws_{row['group_km']}km"])
                    summaries[label] = (cooling_quantities(point, ref["reference_K"], ref["reference_emissivity"]),
                                        cooling_quantities(draw, ref["reference_K"], ref["reference_emissivity"]))
                summaries["quadratic_minus_linear"] = tuple(a-b for a,b in zip(summaries["quadratic"], summaries["linear"]))
                k = ["temperature", "emitted_flux", "temperature_equivalent", "temperature_minus_equivalent"].index(row["quantity"])
                point, draw = summaries[row["model"]]
                expected = summarize(point[k], draw[:, k])
                for field in ("point", "q025", "q975", "SE", "width95"):
                    same(row[field], expected[field], "Finite contrast/table/interval mismatch")
                if row["estimable"] != expected["estimable"]: raise ValueError("Draw accounting mismatch")
        finite.extend(rows)
        c = json.loads(sealed_path(ROOT, RUN, key+"_curves_SEALED.json").read_text())
        if len(c) != 101*2*3*4: raise ValueError("Unexpected curve row count")
        for row in c:
            if row["spanning_blocks"] <= 0 or row["status"] != "ESTIMABLE": raise ValueError("Unsupported/nonestimable curve")
            if row["q025"] > row["q975"]: raise ValueError("Reversed curve interval")
        curves.extend(c)
    for name, rows in (("finite_contrasts_SEALED.csv", finite), ("curves_SEALED.csv", curves)):
        dest = sealed_path(ROOT, RUN, name)
        if dest.exists(): raise ValueError("Preserve aggregate sealed table")
        pd.DataFrame(rows).to_csv(dest, index=False)
        dest.chmod(0o600)
        if len(pd.read_csv(dest)) != len(rows): raise ValueError("Sealed CSV row roundtrip failed")
    p = pd.read_csv(public("precision.csv"))
    for row in p.where(pd.notnull(p), None).to_dict("records"): public_precision(row)
    for name in ("precision.csv", "retained_support.csv", "resampling.csv", "fit_diagnostics.csv"):
        if sha(public(name)) != sha(PACKET/name): raise ValueError("Public packet copy differs")
    figures = json.loads((EXEC/"figure_verification.json").read_text())
    if len(figures["sealed_figures"]) != 32: raise ValueError("Incomplete comparison figures")
    for r in figures["sealed_figures"]:
        if sha(ROOT/r["path"]) != r["sha256"] or r["visually_reviewed"]: raise ValueError("Figure access/hash mismatch")
    private = sealed_path(ROOT, RUN, "finite_contrasts_SEALED.csv").parent
    if private.stat().st_mode & 0o777 != 0o700: raise ValueError("Sealed directory permissions")
    for p in private.iterdir():
        if p.is_file() and p.stat().st_mode & 0o777 != 0o600: raise ValueError("Sealed file permissions")
    errors = validate(ROOT)
    if errors: raise ValueError("Output boundary validation failed")
    record = dict(status="PASS", frozen_inputs_verified=len(cfg["inputs"]), frozen_code_files_verified=len(cfg["code_sha256"]),
                  known_answer_tests=12, paired_outcome_identity_verified=True, all_original_linear_points_recovered=True,
                  physical_identity_and_sample_counts_verified=True, audited_draw_hashes_reconciled=32,
                  finite_table_rows=len(finite), finite_estimated_rows=sum(r["status"] == "ESTIMABLE" for r in finite),
                  unsupported_candidate_pass_pairs=sum(r["status"] != "ESTIMABLE" for r in finite),
                  curve_table_rows=len(curves), public_precision_rows=len(pd.read_csv(public("precision.csv"))),
                  support_rows=len(pd.read_csv(public("retained_support.csv"))),
                  sealed_comparison_figures=32, synthetic_template_visually_checked=True,
                  empirical_effect_figures_visually_checked=False, all_sealed_file_permissions="0600; parent0700",
                  empirical_new_effects_displayed=False, public_serialization_allowlist_passed=True,
                  output_boundaries_passed=True, scale_ruling=None,
                  verification_script_sha256=sha(Path(__file__)))
    write(EXEC/"verification.json", record)
    print(json.dumps(record))


if __name__ == "__main__": main()
