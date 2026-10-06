"""Step 5 internal outcome fitting. No new effect values enter public outputs."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import CONTEXT, emitted_energy
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from .canopy_support import READ_COLUMNS, endpoint_support
from .spatial_review import validate_native_rows
from .quadratic_sensitivity import (
    fit_model, paired_bootstrap, contrast, endpoint_averages, cooling_quantities,
    summarize, public_precision, sealed_path, write_sealed_json,
)

ROOT = Path(__file__).resolve().parents[2]
RUN = "quadratic_step5_20261005"
EXEC = ROOT / "docs/v2/v6_2/execution" / RUN
PACKET = ROOT / "deliverables/Step5_Quadratic_2023_v6_2_20261005"
AUDIT = "docs/v2/v6_2/execution/canopy_support_step5_20261004/execution_freeze.json"
SUPPORT = "deliverables/Step5_Canopy_Support_2023_v6_2_20261004"
REF = "outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json"
RELEASED = "outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv"
CODE = ["src/v6_2_advance/quadratic_sensitivity.py", "src/v6_2_advance/run_quadratic_sensitivity.py",
        "src/v6_2_advance/plot_quadratic_sensitivity.py", "tests/v6_2_advance/test_quadratic_sensitivity.py",
        "src/v6_2_advance/canopy_support.py", "src/v6_2_advance/spatial_review.py",
        "src/urban_cooling_v2/pooled_city_pass.py", "src/urban_cooling_v2/v6_2_output_boundary.py"]
ACTIVE_DOCS = ["AGENTS.md", "docs/v2/v6_2/protocol_v6_2.yml", "docs/v2/v6_2/pilot_plan_v6_2.md",
               "docs/v2/v6_2/decision_log_v6_2.md", "docs/v2/v6_2/prior_thermal_access.md",
               "docs/v2/v6_2/results_review_and_targeted_analysis_plan_20260930.md"]
QUANTITIES = [("temperature", "K"), ("emitted_flux", "W/m2"),
              ("temperature_equivalent", "K"), ("temperature_minus_equivalent", "K")]


def sha(p):
    with Path(p).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def public(name):
    p = guarded_output_path(ROOT, "scientific", f"{RUN}/{name}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, allow_nan=False)+"\n")


def freeze():
    target = EXEC / "execution_freeze.json"
    if target.exists():
        raise ValueError("Execution freeze already exists; preserve it")
    audit = json.loads((ROOT/AUDIT).read_text())
    if str((ROOT/"data").resolve(strict=True)) != audit["data_link_target"]:
        raise ValueError("Data-link target differs from audited target")
    paths = [AUDIT, REF, RELEASED, f"{SUPPORT}/endpoint_support.csv", f"{SUPPORT}/design_resampling.csv"]
    inputs = [dict(path=p, sha256=sha(ROOT/p), role="existing_public_record") for p in paths]
    for spec in audit["passes"]:
        if sha(ROOT/spec["path"]) != spec["sha256"]:
            raise ValueError("Cached native sample checksum changed")
        inputs.append(dict(path=spec["path"], sha256=spec["sha256"], role="internal_paired_native_frame"))
        print(json.dumps(dict(stage="input_verified", city=spec["city"], orbit=spec["orbit"])), flush=True)
    archive = ROOT/"docs/v2/v6_2/archive/before_quadratic_step5_20261005"
    snapshot = []
    for rel in ACTIVE_DOCS:
        out = archive/rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists(): raise ValueError("Prior documentation archive exists")
        shutil.copy2(ROOT/rel, out)
        snapshot.append(dict(path=rel, sha256=sha(out)))
    write(archive/"snapshot.json", dict(files=snapshot, created_utc=datetime.now(timezone.utc).isoformat()))
    displays = {}
    for city in ("phoenix", "atlanta"):
        specs = [p for p in audit["passes"] if p["city"] == city]
        lo = max(p["quantiles"]["0.05"] for p in specs)
        hi = min(p["quantiles"]["0.95"] for p in specs)
        displays[city] = dict(lower=lo, upper=hi, reference=lo, points=101,
                              rule="intersection of audited pass P05-P95; display only, no row exclusion")
    record = dict(created_utc=datetime.now(timezone.utc).isoformat(), record_date_local="2026-10-05",
        authority=dict(request="ok lets do that part of part 5? Is part 5 fully done yet?",
                       interpretation="Authorize internal quadratic fitting and matched linear comparison, resolving Step4 fitting hold",
                       prior_sealing_reply="Not yet—keep new effects sealed", new_effect_display=False,
                       professor_approval=False),
        sample=audit["sample"], passes=audit["passes"], data_link_target=audit["data_link_target"],
        inputs=inputs, code_sha256={p:sha(ROOT/p) for p in CODE},
        settings=dict(candidate_pairs=audit["settings"]["candidate_pairs"],
                      halfwidths_fraction=audit["settings"]["halfwidths_fraction"],
                      reference=json.loads((ROOT/REF).read_text()), displays=displays,
                      mean_model="same original 1km block intercepts, all six frozen controls, unit native-cell weights",
                      protected_basis="raw f plus raw f squared, transformed before separate block centering",
                      baseline="reconstruct linear fit on same cells; verify prior released temperature slope",
                      groups_km=[1, 8], replicates=1000, seed_rule="20261004 + 100000 + orbit; reuse audited design multiplicities",
                      inference="matched percentile bootstrap of each finite contrast and quadratic-minus-linear difference",
                      reference_weights="fixed unit weights on all cells in original blocks spanning endpoints; same for both models",
                      pair_policy="report all15 frozen candidates; no numerical effect for zero-spanning-block pairs; any positive spanning count is only descriptive range support, not a positivity cutoff",
                      curve_policy="101 city-specific canopy points, pointwise intervals, no city mean or simultaneous band",
                      scale_tolerance=None, scale_ruling=None, primary_estimator_replaced=False,
                      new_inclusion_cutoff=None, new_time_inference=False, city_ranking=False,
                      log_or_higher_degree_model_search=False, raw_thermal_raster_access=False,
                      visual_effect_review="deferred under explicit sealing instruction"))
    write(target, record)
    write(EXEC/"scope.json", {"authority":record["authority"], "settings":record["settings"],
                            "status":"FROZEN_BEFORE_OUTCOME_ACCESS"})
    for p in CODE:
        out = EXEC/"archive/frozen_code"/p; out.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT/p, out)
    print(json.dumps(dict(stage="freeze_complete", sources=len(inputs), passes=16, effects="SEALED")), flush=True)


def require_close(actual, expected, message, tolerance=1e-8):
    if not np.allclose(actual, expected, atol=tolerance, rtol=0):
        raise ValueError(message)  # Never print empirical arrays on assertion failure.


def run():
    os.umask(0o077)
    freeze_path = EXEC/"execution_freeze.json"
    cfg = json.loads(freeze_path.read_text())
    if str((ROOT/"data").resolve(strict=True)) != cfg["data_link_target"]:
        raise ValueError("Data-link target changed")
    for p, h in cfg["code_sha256"].items():
        if sha(ROOT/p) != h: raise ValueError("Frozen analysis code changed")
    for item in cfg["inputs"]:
        if sha(ROOT/item["path"]) != item["sha256"]: raise ValueError("Frozen input changed")
    expected = pd.read_csv(ROOT/RELEASED).set_index(["city", "orbit"])
    design_audit = pd.read_csv(ROOT/SUPPORT/"design_resampling.csv").set_index(["city", "orbit", "group_km"])
    support_audit = pd.read_csv(ROOT/SUPPORT/"endpoint_support.csv")
    settings = cfg["settings"]; ref = settings["reference"]
    completions, precision, supporting, resampling, access = [], [], [], [], []
    for spec in cfg["passes"]:
        key = f"{spec['city']}_{spec['orbit']}"
        done = public(key+"_completion.json")
        if done.exists():
            old = json.loads(done.read_text())
            if old["execution_freeze_sha256"] != sha(freeze_path): raise ValueError("Existing run freeze mismatch")
            for rel, h in old["output_sha256"].items():
                if sha(ROOT/rel) != h: raise ValueError("Existing output changed")
            completions.append(old)
            precision.extend(json.loads(public(key+"_precision.json").read_text()))
            supporting.extend(json.loads(public(key+"_support.json").read_text()))
            resampling.extend(json.loads(public(key+"_resampling.json").read_text()))
            access.append(dict(path=spec["path"], columns=[*READ_COLUMNS, "LST_K", "M_W_m2", "emissivity"],
                               purpose="verified completed internal quadratic run"))
            continue
        start = time.monotonic()
        columns = [*READ_COLUMNS, "LST_K", "M_W_m2", "emissivity"]
        access.append(dict(path=spec["path"], columns=columns, purpose="internal paired quadratic outcome fitting"))
        write(EXEC/"access_log.json", access)
        frame = pd.read_parquet(ROOT/spec["path"], columns=columns)
        validate_native_rows(frame)
        if len(frame) != spec["n_cells"] or frame.block.nunique() != spec["n_blocks"]:
            raise ValueError("Original sample counts changed")
        require_close(frame.M_W_m2, emitted_energy(frame.LST_K, frame.emissivity), "Emitted-energy identity failed", 1e-9)
        models = [fit_model(frame, quadratic=q) for q in (False, True)]
        for model in models:
            if model.design.diagnostics["removed_context_terms"]:
                raise ValueError("Unexpected control removal from audited design")
        require_close(models[0].coefficients[0, 0]*.1,
                      expected.loc[(spec["city"], spec["orbit"]), "gradient_K_per_10pp"],
                      "Original released temperature coefficient not recovered")
        draws_by_size = {}; audits = []
        for size in settings["groups_km"]:
            draws, audit = paired_bootstrap(*models, group_km=size, replicates=settings["replicates"],
                                            seed=20261004+100000+spec["orbit"])
            old = design_audit.loc[(spec["city"], spec["orbit"], size)]
            for field in ("draw_multiplicity_sha256", "linear_estimable", "quadratic_estimable", "paired_estimable", "paired_failed"):
                if audit[field] != old[field]: raise ValueError("Outcome bootstrap differs from frozen design-only audit")
            draws_by_size[size] = draws
            audits.append(dict(city=spec["city"], orbit=spec["orbit"], date=spec["date"], **audit))
        sealed_outputs = []
        arrays = {}
        for j, label in enumerate(("linear", "quadratic")):
            m = models[j]
            arrays.update({label+"_coefficients":m.coefficients, label+"_names":np.asarray(m.design.names),
                           label+"_block_x_means":m.design.means, label+"_block_y_means":m.block_y_means})
            for size, draws in draws_by_size.items(): arrays[f"{label}_draws_{size}km"] = draws[j]
        arrays["block_labels"] = models[0].design.block_labels.astype(str)
        arrays["outcomes"] = np.asarray(["LST_K", "M_W_m2"])
        p = sealed_path(ROOT, RUN, key+"_models_SEALED.npz")
        with p.open("xb") as stream: np.savez_compressed(stream, **arrays)
        p.chmod(0o600); sealed_outputs.append(p)
        effects, pub, support_rows = [], [], []
        for pair in settings["candidate_pairs"]:
            f0, f1 = pair["f0"], pair["f1"]
            mask = None
            for width in settings["halfwidths_fraction"]:
                s, _, mask = endpoint_support(frame, f0, f1, width)
                old = support_audit[(support_audit.city.eq(spec["city"])) & (support_audit.orbit.eq(spec["orbit"])) &
                                    support_audit.pair_id.eq(pair["pair_id"]) & np.isclose(support_audit.halfwidth_fraction, width)]
                if len(old) != 1: raise ValueError("Missing audited endpoint row")
                for name in ("spanning_blocks", "reference_cells", "lower_cells", "upper_cells"):
                    if s[name] != old.iloc[0][name]: raise ValueError("Endpoint support changed")
                support_rows.append(dict(city=spec["city"], orbit=spec["orbit"], date=spec["date"], pair_id=pair["pair_id"], **s))
            meta = dict(city=spec["city"], orbit=spec["orbit"], date=spec["date"], **pair,
                        support_status="BLOCK_RANGE_ONLY" if mask.any() else "NO_SPANNING_BLOCKS")
            if not mask.any():
                effects.append({**meta, "status":"NOT_ESTIMATED_NO_REFERENCE_BLOCKS"}); continue
            for size, draws in draws_by_size.items():
                points, boot = [], []
                for model, draw in zip(models, draws):
                    point, values = contrast(model, draw, f0, f1)
                    means = endpoint_averages(model, frame.loc[mask], f0, f1)
                    require_close(means[1]-means[0], point, "Basis-aware averaged predictions differ from analytic contrast", 1e-9)
                    points.append(cooling_quantities(point, ref["reference_K"], ref["reference_emissivity"]))
                    boot.append(cooling_quantities(values, ref["reference_K"], ref["reference_emissivity"]))
                points.append(points[1]-points[0]); boot.append(boot[1]-boot[0])
                for label, point, values in zip(("linear", "quadratic", "quadratic_minus_linear"), points, boot):
                    for k, (quantity, units) in enumerate(QUANTITIES):
                        stats = summarize(point[k], values[:, k])
                        effects.append(dict(**meta, group_km=size, model=label, quantity=quantity, units=units, **stats))
                        pub.append(public_precision(dict(**meta, group_km=size, model=label, quantity=quantity, units=units,
                            requested=settings["replicates"], estimable=stats["estimable"], failed=stats["failed"],
                            SE=stats["SE"], width95=stats["width95"], effect_status="SEALED_USER_REQUEST")))
        p = write_sealed_json(ROOT, RUN, key+"_finite_contrasts_SEALED.json", effects); sealed_outputs.append(p)
        display = settings["displays"][spec["city"]]
        grid = np.linspace(display["lower"], display["upper"], display["points"])
        bounds = frame.groupby("block").canopy_fraction.agg(["min", "max"])
        curve = []
        for f in grid:
            span = int(((bounds["min"] <= display["reference"]) & (bounds["max"] >= f)).sum())
            if span == 0: raise ValueError("Curve grid lacks reference-range support")
            for size, draws in draws_by_size.items():
                pts, vals = [], []
                for model, draw in zip(models, draws):
                    point, values = contrast(model, draw, display["reference"], float(f))
                    pts.append(cooling_quantities(point, ref["reference_K"], ref["reference_emissivity"]))
                    vals.append(cooling_quantities(values, ref["reference_K"], ref["reference_emissivity"]))
                pts.append(pts[1]-pts[0]); vals.append(vals[1]-vals[0])
                for label, point, values in zip(("linear", "quadratic", "quadratic_minus_linear"), pts, vals):
                    for k, (quantity, units) in enumerate(QUANTITIES):
                        curve.append(dict(city=spec["city"], orbit=spec["orbit"], date=spec["date"],
                            canopy_fraction=float(f), reference_canopy=display["reference"], spanning_blocks=span,
                            group_km=size, model=label, quantity=quantity, units=units, **summarize(point[k], values[:, k])))
        p = write_sealed_json(ROOT, RUN, key+"_curves_SEALED.json", curve); sealed_outputs.append(p)
        hist, edges = np.histogram(frame.canopy_fraction, bins=np.linspace(0, 1, 41))
        write(public(key+"_canopy_histogram.json"), dict(city=spec["city"], orbit=spec["orbit"], edges=edges.tolist(), cells=hist.tolist()))
        write(public(key+"_precision.json"), pub); write(public(key+"_support.json"), support_rows)
        write(public(key+"_resampling.json"), audits)
        public_files = [public(key+x) for x in ("_precision.json", "_support.json", "_resampling.json", "_canopy_histogram.json")]
        completed = dict(city=spec["city"], orbit=spec["orbit"], date=spec["date"], n_cells=len(frame),
                         n_blocks=spec["n_blocks"], linear_rank=len(models[0].design.names), quadratic_rank=len(models[1].design.names),
                         controls_retained=6, original_linear_recovered=True, paired_draws_requested=2000,
                         paired_draws_estimable=sum(a["paired_estimable"] for a in audits),
                         paired_draws_failed=sum(a["paired_failed"] for a in audits),
                         supported_candidate_pairs=sum(1 for r in support_rows if r["halfwidth_fraction"] == .01 and r["spanning_blocks"] > 0),
                         execution_freeze_sha256=sha(freeze_path), source_sha256=spec["sha256"],
                         effect_status="SEALED_USER_REQUEST", elapsed_seconds=round(time.monotonic()-start, 3),
                         output_sha256={str(p.relative_to(ROOT)):sha(p) for p in [*sealed_outputs, *public_files]})
        write(done, completed); completions.append(completed)
        precision.extend(pub); supporting.extend(support_rows); resampling.extend(audits)
        print(json.dumps({k:completed[k] for k in ("city", "orbit", "n_cells", "paired_draws_estimable", "paired_draws_failed", "elapsed_seconds", "effect_status")}), flush=True)
        del frame, models, draws_by_size, arrays, effects, curve; gc.collect()
    pd.DataFrame(precision).to_csv(public("precision.csv"), index=False)
    pd.DataFrame(supporting).to_csv(public("retained_support.csv"), index=False)
    pd.DataFrame(resampling).to_csv(public("resampling.csv"), index=False)
    pd.DataFrame([{k:v for k,v in c.items() if k != "output_sha256"} for c in completions]).to_csv(public("fit_diagnostics.csv"), index=False)
    completion = dict(status="INTERNAL_FITTING_COMPLETE_EFFECT_REVIEW_DEFERRED", passes=len(completions),
                      new_paired_quadratic_models=len(completions), reconstructed_paired_linear_models=len(completions),
                      cell_pass_observations=sum(c["n_cells"] for c in completions),
                      paired_configurations=len(resampling), paired_draws_requested=32000,
                      paired_draws_estimable=sum(c["paired_draws_estimable"] for c in completions),
                      paired_draws_failed=sum(c["paired_draws_failed"] for c in completions),
                      effect_display=False, interpretation_and_visual_review="DEFERRED_SEALED",
                      scale_ruling=None, new_time_inference=False, completed_utc=datetime.now(timezone.utc).isoformat())
    write(public("completion.json"), completion)
    PACKET.mkdir(parents=True, exist_ok=True)
    for name in ("precision.csv", "retained_support.csv", "resampling.csv", "fit_diagnostics.csv", "completion.json"):
        shutil.copy2(public(name), PACKET/name)
    print(json.dumps(completion), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    if args.freeze: freeze()
    else: run()
