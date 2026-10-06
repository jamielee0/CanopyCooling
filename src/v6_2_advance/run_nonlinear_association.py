"""Run the user-authorized 2023 curve check on existing paired native cells."""
from pathlib import Path
import sys
import json
import hashlib
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from urban_cooling_v2.pooled_city_pass import emitted_energy
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from v6_2_advance.nonlinear_association import (
    fit_curve, curve_difference, partial_cooling, linear_check, summarize_bins,
)

RUN = "nonlinear_association_20260930"
DESIGN = ROOT / "docs/v2/v6_2/execution" / RUN


def dest(role, name):
    p = guarded_output_path(ROOT, role, RUN + "/" + name)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_json(path, record):
    path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")


def main():
    freeze = json.loads((DESIGN / "numeric_support_freeze.json").read_text())
    assert digest(DESIGN / "design.json") == freeze["design_sha256"]
    assert str((ROOT / "data").resolve()) == freeze["data_link_target"]
    assert (ROOT / "data").is_dir()
    source = ROOT / "outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv"
    released = pd.read_csv(source).set_index(["city", "orbit"])
    code = [Path(__file__), ROOT / "src/v6_2_advance/nonlinear_association.py",
            ROOT / "src/urban_cooling_v2/pooled_city_pass.py",
            ROOT / "tests/v6_2_advance/test_nonlinear_association.py"]
    record = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "user_authorization": "Display exploratory nonlinear LST associations and observed bins, requested 30 September 2026.",
              "code_sha256": {str(p.relative_to(ROOT)): digest(p) for p in code},
              "numeric_support_sha256": digest(DESIGN / "numeric_support_freeze.json"),
              "source_linear_table_sha256": digest(source),
              "model": "Restricted cubic spline, original block intercepts/context, paired LST/emitted energy",
              "prior_time_comparisons_opened": False, "prior_robustness_effects_opened": False,
              "scale_ruling": "pending", "status": "exploratory, after prior linear-effect disclosure"}
    execution = dest("scientific", "execution_freeze.json")
    if execution.exists():
        old = json.loads(execution.read_text())
        for key in ["code_sha256", "numeric_support_sha256", "source_linear_table_sha256"]:
            assert old[key] == record[key], "Frozen execution changed"
    else:
        write_json(execution, record)
    dest("sealed", "placeholder").parent.chmod(0o700)
    summaries, errors = [], []
    for spec in freeze["passes"]:
        city, orbit = spec["city"], spec["orbit"]
        key = f"{city}_{orbit}"
        result = dest("scientific", key + "_completion.json")
        if result.exists():
            summaries.append(json.loads(result.read_text()))
            print(json.dumps({"city": city, "orbit": orbit, "status": "verified existing fit"}), flush=True)
            continue
        try:
            path = ROOT / spec["path"]
            assert digest(path) == spec["sha256"]
            d = pd.read_parquet(path)
            assert len(d) == spec["n_cells"]
            assert not d.duplicated(["native_crs", "native_x", "native_y"]).any()
            np.testing.assert_allclose(d.M_W_m2, emitted_energy(d.LST_K, d.emissivity), rtol=1e-12, atol=1e-9)
            settings = freeze["cities"][city]
            lo, hi = settings["display_lower"], settings["display_upper"]
            ref, knots = settings["reference_canopy"], settings["knots"]
            # Include integer canopy percentages as well as a smooth display grid.
            integers = np.arange(np.ceil(lo*100), np.floor(hi*100)+1) / 100
            grid = np.unique(np.r_[np.linspace(lo, hi, 201), integers])
            d, fit = fit_curve(d, knots)
            base = linear_check(d, fit)
            expected = float(released.loc[(city, orbit), "gradient_K_per_10pp"])
            np.testing.assert_allclose(base[0, 0]*.1, expected, rtol=1e-8, atol=1e-8)
            point, draws = curve_difference(fit, knots, grid, ref)
            valid = np.isfinite(draws).all(axis=(1, 2))
            qlo, qhi = np.quantile(draws[valid, :, 0], [.025, .975], axis=0)
            bounds = d.groupby("block").canopy_fraction.agg(["min", "max"])
            spans = np.array([((bounds["min"] <= min(ref, x)) & (bounds["max"] >= max(ref, x))).sum() for x in grid])
            table = pd.DataFrame({"city": city, "orbit": orbit, "date": spec["date"],
                                  "canopy_fraction": grid, "reference_canopy_fraction": ref,
                                  "cooling_C": point[:, 0], "q025_8km_pointwise_C": qlo,
                                  "q975_8km_pointwise_C": qhi,
                                  "linear_cooling_C": -base[0, 0]*(grid-ref),
                                  "blocks_spanning_reference_and_target": spans})
            table.to_csv(dest("scientific", key + "_curve.csv"), index=False)
            bins = pd.DataFrame(summarize_bins(d, partial_cooling(d, fit, knots, ref), settings["bin_edges"]))
            bins.insert(0, "orbit", orbit)
            bins.insert(0, "city", city)
            bins.to_csv(dest("scientific", key + "_bins.csv"), index=False)
            sealed = dest("sealed", key + "_paired_fit_SEALED.npz")
            np.savez_compressed(sealed, coefficients=fit.coefficients,
                                bootstrap_coefficients=fit.bootstrap_coefficients,
                                predictor_names=fit.predictor_names, outcome_names=fit.outcome_names,
                                knots=knots, reference_canopy=ref)
            sealed.chmod(0o600)
            summary = {"city": city, "orbit": orbit, "date": spec["date"],
                       "n_cells": len(d), "n_blocks": fit.diagnostics["n_blocks"],
                       "resampling_groups": fit.diagnostics["resampling_groups"],
                       "design_rank": fit.diagnostics["design_rank"],
                       "bootstrap_requested": 1000, "bootstrap_estimable": int(valid.sum()),
                       "bootstrap_failed": int((~valid).sum()),
                       "original_linear_gradient_reproduced": True,
                       "source_sha256": spec["sha256"], "minimum_spanning_blocks_on_grid": int(spans.min()),
                       "plot_reference_canopy": ref, "plot_upper_canopy": hi,
                       "status": "estimated; LST curve release authorized"}
            write_json(result, summary)
            summaries.append(summary)
            print(json.dumps(summary), flush=True)
            del d, fit, draws
        except (AssertionError, ValueError, np.linalg.LinAlgError) as exc:
            failure = {"city": city, "orbit": orbit, "status": "NOT_ESTIMABLE_OR_VERIFICATION_FAILED", "reason": str(exc)}
            errors.append(failure)
            write_json(dest("scientific", "failures.json"), errors)
            print(json.dumps(failure), flush=True)
    pd.DataFrame(summaries).to_csv(dest("scientific", "fit_diagnostics.csv"), index=False)
    write_json(dest("scientific", "completion.json"), {"fits": len(summaries), "requested": 16,
               "failures": errors, "completed_utc": datetime.now(timezone.utc).isoformat(),
               "primary_model_replaced": False, "new_time_model": False})
    if len(summaries) != 16 or errors:
        raise SystemExit("Incomplete curve check; failures recorded, no rescue selection")


if __name__ == "__main__":
    main()
