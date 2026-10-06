"""Execute Step 3 internally; display only predictor support and precision.

The user explicitly chose to keep all new effects sealed on 4 October 2026.
No empirical time-contrast file is in the read allowlist. Historical models and
native frames are read, never overwritten; no thermal raster is rebuilt.
"""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import CONTEXT, PooledFit
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from .spatial_review import (
    OUTCOMES, PRECISION_FIELDS, block_stats, common_ids, digest, identity_hash,
    joint_bootstrap, paired_scale, predictor_distribution, public_precision,
    reference_support, summary, validate_native_rows, write_sealed_json,
)

ROOT = Path(__file__).resolve().parents[2]
RUN = "spatial_scale_review_20261004"
EXEC = ROOT/"docs/v2/v6_2/execution/spatial_scale_review_20261004"
OUT = ROOT/"deliverables/Spatial_Scale_Review_2023_v6_2_20261004"
OLD = "outputs/v6_2/scientific/phoenix_robustness_20260923"
OLD_SEALED = "outputs/v6_2/sealed_coefficients/phoenix_robustness_20260923"
REF = "outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json"
SHIFTS = ((-1, 0), (1, 0), (0, -1), (0, 1))
PREDICTORS = ("canopy_fraction", *CONTEXT)
SUPPORT_COLUMNS = ("cell_id", "block", *PREDICTORS, "x", "y", "native_crs", "native_x", "native_y")
CODE = (
    "src/v6_2_advance/spatial_review.py", "src/v6_2_advance/run_spatial_review.py",
    "src/v6_2_advance/plot_spatial_review.py", "tests/v6_2_advance/test_spatial_review.py",
    "src/urban_cooling_v2/pooled_city_pass.py", "src/urban_cooling_v2/pilot_scale.py",
    "src/v6_2_advance/run_robustness_completion.py", "src/v6_2_advance/finish_robustness_comparisons.py",
    "src/urban_cooling_v2/v6_2_output_boundary.py",
    "docs/v2/v6_2/execution/spatial_scale_review_20261004/build_public_tables.mjs",
)


def P(name): return guarded_output_path(ROOT, "scientific", f"{RUN}/{name}")
def S(name): return guarded_output_path(ROOT, "sealed", f"{RUN}/{name}")


def write_public_json(name, value):
    path = P(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    return path


def freeze_inputs():
    EXEC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = EXEC/"execution_freeze.json"
    if dest.exists(): raise ValueError("Preserve immutable Step3 freeze; use --run")
    scope = json.loads((ROOT/"docs/v2/v6_2/execution/results_review_20261004/scope.json").read_text())
    passes = scope["main_pilot"]["pass_identities"]
    source_support = json.loads((ROOT/"docs/v2/v6_2/execution/nonlinear_association_20260930/numeric_support_freeze.json").read_text())
    known_frame_hashes = {(r["city"], str(r["orbit"]), r["run_id"]): r["sha256"] for r in source_support["passes"]}
    sources = {
        REF, OLD+"/execution_freeze.json", OLD+"/precision.csv", OLD+"/common_cell_support.json",
        OLD+"/common_cell_retention.csv", OLD+"/registration_support.csv", OLD+"/completion.json",
        OLD+"/matched_support_comparison_freeze.json", OLD+"/matched_support_comparison_validation.json",
        OLD_SEALED+"/registration_matched_support_comparisons_SEALED.json",
        "docs/v2/v6_2/execution/results_review_20261004/scope.json",
        "docs/v2/v6_2/execution/nonlinear_association_20260930/numeric_support_freeze.json",
        "deliverables/Results_Review_2023_v6_2_20261004/pass_results_long.csv",
        "docs/v2/v6_2/execution/phoenix_execution_manifest.json",
        "docs/v2/v6_2/execution/atlanta_execution_manifest.json",
        "docs/v2/v6_2/execution/advance_20260921/phoenix_execution_manifest.json",
        "outputs/v6_2/scientific/pooled_pilot_20260919_phoenix/residual_spatial_diagnostics.csv",
        "outputs/v6_2/scientific/pooled_pilot_20260919_atlanta/residual_spatial_diagnostics.csv",
    }
    for r in passes:
        run, orbit = r["run_id"], str(r["orbit"])
        prefix = f"outputs/v6_2/sealed_coefficients/{run}/{orbit}_"
        sources.add(prefix+"paired_native_cells_SEALED.parquet")
        sources.update(prefix+v+"_SEALED.npz" for v in ("paired_primary", "spatial_8km"))
        sources.add(f"outputs/v6_2/scientific/{run}/precision.csv")
        if r["city"] != "phoenix": continue
        sources.add(f"{OLD_SEALED}/{orbit}_common_cells_all11_SEALED.npz")
        if "extension" in run:
            sources.add(f"{OLD}/{orbit}_baseline_rebuild_validation.json")
            for dx, dy in ((0, 0), *SHIFTS):
                sources.add(f"{OLD_SEALED}/{orbit}_registration_fixed_support_dx{dx}_dy{dy}_SEALED.npz")
                if dx or dy: sources.add(f"{OLD_SEALED}/{orbit}_registration_dx{dx}_dy{dy}_SEALED.npz")
        else:
            sources.update(prefix+f"registration_dx{dx}_dy{dy}_SEALED.npz" for dx, dy in SHIFTS)
    entries = []
    for i, p in enumerate(sorted(sources), 1):
        h = digest(ROOT/p)
        entries.append(dict(path=p, sha256=h, bytes=(ROOT/p).stat().st_size,
                            role="sealed_input" if "sealed_coefficients" in Path(p).parts else "public_record"))
        if p.endswith("paired_native_cells_SEALED.parquet"):
            r = next(r for r in passes if f"/{r['run_id']}/{r['orbit']}_" in p)
            if h != known_frame_hashes[(r["city"], str(r["orbit"]), r["run_id"])]: raise ValueError("Cached native frame changed since predictor freeze")
        if i % 20 == 0: print(json.dumps({"stage": "input_hashing", "completed": i, "total": len(sources)}), flush=True)
    dest.write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(), "record_date_local": "2026-10-04",
        "authority": {"request": "yes do the next step", "plan_step": 3,
                      "user_tolerance_reply": "Not yet—keep new effects sealed", "internal_computation_authorized": True,
                      "new_effect_display_authorized": False},
        "status": "FROZEN_BEFORE_NEW_COMPARISONS", "passes": passes,
        "data_link_target": str((ROOT/"data").resolve(strict=True)),
        "design": {"Phoenix_common_cell_passes": 11, "paired_scale_passes": 16,
                   "joint_spatial_groups_km": [1, 8], "replicates_per_configuration": 1000,
                   "seed_rule": "20261004 + integer orbit; fresh identical multiplicities applied to original/common; fixed seed for each group-size sensitivity",
                   "multiplicity_universe": "union of original/common physical occupied blocks or 8km groups; common missing blocks contribute zero",
                   "mean_models": "unchanged archived canopy/context designs; reconstruct original/common point estimates before bootstrap",
                   "point_recovery_absolute_numerical_tolerance": 1e-8,
                   "numerical_tolerance_is_not_scientific_agreement_margin": True,
                   "reference": "hold historical September19 f0/f1/Tref/emissivity fixed; audit block support for all16 without reselection",
                   "paired_scale_uncertainty": "same archived T/M draws; exact fourth-root transform in each valid draw; report nonpositive anchor/nonestimability",
                   "reference_sensitivities": {"temperature_offsets_K": [-10, 0, 10], "emissivity_offsets": [-.01, 0, .01], "upper_emissivity_cap": .999},
                   "registration_fixed_support": "validate existing24 differences by identical physical block labels, outcomes, complete-case counts, seeds, algorithm and actual array summaries",
                   "registration_available_support": "44 Phoenix shifted-minus-original points; separate constituent intervals only; no unsupported paired difference interval",
                   "predictor_distributions": "cell-weighted original/retained/excluded, all7 predictor variables; min/max and P1,5,10,25,50,75,90,95,99 plus mean/SD",
                   "map": "native cell centres of union of11 original footprints and their exact intersection; no interpolated LST",
                   "support_threshold": None, "empirical_time_comparisons": 0, "new_thermal_raster_reads": 0,
                   "scale_tolerance": None, "scale_ruling": "not made; historical promotion rule excluded"},
        "inputs": entries, "code_at_freeze": [{"path": p, "sha256": digest(ROOT/p)} for p in CODE],
    }, indent=2)+"\n")
    print(json.dumps({"stage": "freeze_complete", "sources": len(entries), "new_effects": "SEALED_USER_REQUEST"}), flush=True)


class Reader:
    def __init__(self, freeze):
        self.freeze = freeze
        self.inputs = {r["path"]: r["sha256"] for r in freeze["inputs"]}
        self.checked = set()
        self.access = []
        if str((ROOT/"data").resolve(strict=True)) != freeze["data_link_target"]: raise ValueError("Changed data-link target")

    def path(self, p, purpose):
        if p not in self.inputs or "time_contrasts" in p: raise ValueError("Outside Step3 input allowlist")
        if p not in self.checked:
            if digest(ROOT/p) != self.inputs[p]: raise ValueError("Frozen input checksum changed")
            self.checked.add(p)
        self.access.append(dict(path=p, purpose=purpose))
        return ROOT/p

    def json(self, p): return json.loads(self.path(p, "record_read").read_text())
    def csv(self, p): return pd.read_csv(self.path(p, "table_read"), dtype={"orbit": str})
    def frame(self, p, columns):
        purpose = "predictor_only_columns" if set(columns).issubset(SUPPORT_COLUMNS) else "internal_paired_outcome_columns"
        return pd.read_parquet(self.path(p, purpose), columns=list(columns))

    def model(self, p):
        with np.load(self.path(p, "internal_sealed_model_and_draw_read"), allow_pickle=False) as z:
            d = {k: z[k] for k in ("coefficients", "bootstrap_coefficients", "predictor_names", "outcome_names", "block_labels", "block_x_means", "block_y_means") if k in z.files}
        metadata = ("predictor_names", "outcome_names", "block_labels", "block_x_means", "block_y_means")
        if any(k not in d for k in metadata):
            # The original ten-pass stress runner saved coefficient/draw arrays
            # only. Its archived code changes grouping while preserving the
            # point model. Recover metadata from the corresponding primary
            # file only after confirming the identical coefficient matrix.
            if "_spatial_8km_SEALED.npz" not in p: raise ValueError("Unexpected incomplete archived model metadata")
            base = self.model(p.replace("_spatial_8km_SEALED.npz", "_paired_primary_SEALED.npz"))
            assert_close(d["coefficients"], base["coefficients"], "Stress model differs from primary metadata source", 1e-8)
            d.update({k: base[k] for k in metadata if k not in d})
        if list(d["outcome_names"]) != list(OUTCOMES) or d["predictor_names"][0] != "canopy_fraction": raise ValueError("Unexpected archived paired design")
        if d["bootstrap_coefficients"].shape != (1000, len(d["predictor_names"]), 2): raise ValueError("Unexpected archived draw dimensions")
        if len(set(d["block_labels"])) != len(d["block_labels"]): raise ValueError("Nonunique archived physical block labels")
        return d


def assert_close(a, b, message, tolerance=1e-10):
    # Never use an assertion helper that prints empirical values on failure.
    if np.shape(a) != np.shape(b) or not np.allclose(a, b, rtol=0, atol=tolerance, equal_nan=False):
        raise ValueError(message)


def precision_row(r, *, kind, variant, group_km, cells, blocks, groups, requested, estimable, t_se, t_width, m_se, m_width, pairing, method):
    return public_precision(dict(city=r["city"], orbit=str(r["orbit"]), date=r["date"], kind=kind, variant=variant,
        source_run_id=r["run_id"], group_km=group_km, n_cells=cells, n_blocks=blocks, groups=groups,
        bootstrap_requested=requested, bootstrap_estimable=estimable, bootstrap_failed=requested-estimable,
        T_SE_K_per_10pp=t_se, T_width95_K_per_10pp=t_width, M_SE_W_m2_per_10pp=m_se,
        M_width95_W_m2_per_10pp=m_width, interval_method=method, pairing_status=pairing, effect_status="SEALED_USER_REQUEST"))


def from_existing(r, p, kind):
    return precision_row(r, kind=kind, variant=str(p["variant"]), group_km=8 if str(p["variant"])=="spatial_8km" else 1,
        cells=int(p["n_cells"]), blocks=int(p["n_blocks"]), groups=int(p["resampling_groups"]),
        requested=int(p["bootstrap_requested"]), estimable=int(p["bootstrap_estimable"]),
        t_se=float(p["LST_K_SE_per_10pp"]), t_width=float(p["LST_K_bootstrap_width_95_per_10pp"]),
        m_se=float(p["M_W_m2_SE_per_10pp"]), m_width=float(p["M_W_m2_bootstrap_width_95_per_10pp"]),
        pairing="constituent precision only; not a difference interval", method="existing whole-block percentile bootstrap")


def run():
    from .plot_spatial_review import plot_public_support, plot_sealed_reviews
    freeze = json.loads((EXEC/"execution_freeze.json").read_text())
    reader = Reader(freeze)
    passes = freeze["passes"]
    phoenix = sorted([r for r in passes if r["city"]=="phoenix"], key=lambda r: r["date"])
    added = [r for r in phoenix if "extension" in r["run_id"]]
    old_precision = reader.csv(OLD+"/precision.csv")
    old_common = reader.json(OLD+"/common_cell_support.json")
    old_registration = reader.csv(OLD+"/registration_support.csv")
    old_validation = reader.json(OLD+"/matched_support_comparison_validation.json")
    old_match_freeze = reader.json(OLD+"/matched_support_comparison_freeze.json")
    robust_freeze = reader.json(OLD+"/execution_freeze.json")
    if old_match_freeze["code_sha256"] != digest(ROOT/"src/v6_2_advance/finish_robustness_comparisons.py"):
        raise ValueError("Archived pairing algorithm source no longer matches freeze")
    algorithm_hashes = robust_freeze["specification"]["code_sha256"]
    for code in ("src/v6_2_advance/run_robustness_completion.py", "src/urban_cooling_v2/pooled_city_pass.py"):
        if algorithm_hashes[code] != digest(ROOT/code): raise ValueError("Archived model/bootstrap algorithm changed")
    frame_path = lambda r: f"outputs/v6_2/sealed_coefficients/{r['run_id']}/{r['orbit']}_paired_native_cells_SEALED.parquet"
    model_path = lambda r, variant: f"outputs/v6_2/sealed_coefficients/{r['run_id']}/{r['orbit']}_{variant}_SEALED.npz"
    id_frames = []
    for r in phoenix:
        id_frames.append(reader.frame(frame_path(r), ["cell_id"]))
    ids = common_ids(id_frames)
    if len(ids) != old_common["common_cells"] or identity_hash(ids) != old_common["identity_sha256"]:
        raise ValueError("All-eleven common footprint identity changed")
    del id_frames
    reference = reader.json(REF)
    primary_precision = {run: reader.csv(f"outputs/v6_2/scientific/{run}/precision.csv") for run in sorted({r["run_id"] for r in passes})}
    table = reader.csv("deliverables/Results_Review_2023_v6_2_20261004/pass_results_long.csv")
    table = table[table.variant.eq("original")]
    public_precision_rows, distributions, footprint_rows = [], [], []
    support_validation, common_effects, paired_scales, ref_sens, available_effects = [], [], [], [], []
    cdf = []
    union_points = {}
    shared_predictors = None
    coordinate_columns = ["x", "y", "native_crs", "native_x", "native_y", "block"]
    cdf_prob = np.linspace(0, 1, 201)
    reference_meta = {}
    for r in passes:
        city, orbit = r["city"], str(r["orbit"])
        frame = reader.frame(frame_path(r), SUPPORT_COLUMNS)
        validate_native_rows(frame)
        q = table[(table.city.eq(city)) & (table.orbit.eq(orbit)) & (table.source_run_id.eq(r["run_id"]))]
        if len(q)!=1 or len(frame)!=int(q.iloc[0].n_cells): raise ValueError("Original predictor support does not reconcile")
        ref_mask, ref_support = reference_support(frame, reference["f0"], reference["f1"])
        ref_record = dict(city=city, orbit=orbit, date=r["date"], source_run_id=r["run_id"], original_cells=len(frame),
            original_blocks=int(frame.block.nunique()), reference_f0=reference["f0"], reference_f1=reference["f1"],
            reference_cells=ref_support["reference_cells"], reference_supporting_blocks=ref_support["supporting_blocks"],
            reference_status=ref_support["status"], common_all11_cells=None, common_all11_blocks=None,
            common_all11_area_km2=None, common_all11_retained_fraction=None, excluded_cells=None,
            common_scope="Phoenix only" if city=="phoenix" else "NOT_APPLICABLE_PHOENIX_INTERSECTION")
        for prefix in ("original", "common"):
            for field in ("maximum_block_information_share", "top_five_block_information_share", "effective_information_blocks", "maximum_slope_design_leverage", "within_block_canopy_variance", "residualized_canopy_Sxx"):
                ref_record[prefix+"_"+field] = None
        for field in ("maximum_block_information_share", "top_five_block_information_share", "effective_information_blocks", "maximum_slope_design_leverage", "within_block_canopy_variance", "residualized_canopy_Sxx"):
            ref_record["original_"+field] = float(q.iloc[0][field])
        if city=="phoenix":
            keep = frame.cell_id.isin(ids).to_numpy()
            common = frame.loc[keep].set_index("cell_id", drop=False).loc[ids].reset_index(drop=True)
            aligned = common[list(PREDICTORS)+coordinate_columns]
            if shared_predictors is None: shared_predictors=aligned.copy()
            elif not aligned.equals(shared_predictors): raise ValueError("Common cells differ in predictors/physical coordinates across passes")
            for name, subset in (("original", frame), ("retained_all11", common), ("excluded_from_all11", frame.loc[~keep])):
                for variable in PREDICTORS:
                    values = subset[variable].to_numpy(float)
                    unit = "m" if variable in ("elevation", "distance_to_water") else "fraction"
                    distributions.append(dict(city=city, orbit=orbit, date=r["date"], source_run_id=r["run_id"],
                        population=name, variable=variable, unit=unit, **predictor_distribution(values)))
                    if name != "original":
                        cdf.append(dict(orbit=orbit, date=r["date"], population=name, variable=variable,
                            unit=unit, quantiles=np.quantile(values, cdf_prob).tolist(), probabilities=cdf_prob.tolist()))
            for cell, x, y in frame[["cell_id", "x", "y"]].itertuples(index=False, name=None):
                if cell not in union_points: union_points[cell] = (x, y)
            ref_record.update(common_all11_cells=len(common), common_all11_blocks=int(common.block.nunique()),
                common_all11_area_km2=len(common)*.0049, common_all11_retained_fraction=len(common)/len(frame), excluded_cells=len(frame)-len(common))
            cp = old_precision[(old_precision.pass_id.eq(f"phoenix:{orbit}")) & old_precision.variant.eq("common_cells_all11")]
            if len(cp)!=1: raise ValueError("Common predictor-information identity ambiguous")
            for field in ("maximum_block_information_share", "top_five_block_information_share", "effective_information_blocks", "maximum_slope_design_leverage", "within_block_canopy_variance", "residualized_canopy_Sxx"):
                source = "within_block_variance" if field=="within_block_canopy_variance" else field
                ref_record["common_"+field] = float(cp.iloc[0][source])
            del common
        reference_meta[(city, orbit)] = (ref_support, ref_mask)
        footprint_rows.append(ref_record)
        # Read outcomes only for joint reconstruction and paired-scale checks.
        for name in (*OUTCOMES, "emissivity"):
            values = reader.frame(frame_path(r), [name])[name].to_numpy()
            frame[name] = values
        model = reader.model(model_path(r, "paired_primary"))
        names = list(model["predictor_names"])
        if names != list(PREDICTORS): raise ValueError("Frozen primary predictor design differs; report rather than silently redesign")
        source_coef = model["coefficients"]
        if city=="phoenix":
            common = frame.set_index("cell_id", drop=False).loc[ids].reset_index(drop=True)
            common_model = reader.model(f"{OLD_SEALED}/{orbit}_common_cells_all11_SEALED.npz")
            original_stats = block_stats(frame, names)
            common_stats = block_stats(common, list(common_model["predictor_names"]))
            assert_close(original_stats.solve(), source_coef, "Original point reconstruction failed", 1e-8)
            assert_close(common_stats.solve(), common_model["coefficients"], "Common-cell point reconstruction failed", 1e-8)
            if not np.array_equal(original_stats.labels, model["block_labels"]) or not np.array_equal(common_stats.labels, common_model["block_labels"]):
                raise ValueError("Reconstructed physical blocks differ from archived fits")
            support_validation.append(dict(city=city, orbit=orbit, exact_native_identity=True, predictor_coordinates_match=True,
                original_point_recovered=True, common_point_recovered=True, original_cells=len(frame), common_cells=len(common)))
            for size in (1, 8):
                joint = joint_bootstrap(original_stats, common_stats, replicates=1000, seed=20261004+int(orbit), group_km=size)
                delta = joint["points"][1]-joint["points"][0]
                result = summary(delta, joint["difference_draws"])
                record = dict(city=city, orbit=orbit, date=r["date"], source_run_id=r["run_id"], group_km=size,
                    original=summary(joint["points"][0], joint["draws"][:, 0]), common=summary(joint["points"][1], joint["draws"][:, 1]),
                    common_minus_original=result, method="fresh joint multiplicities over original/common union", groups=joint["groups"],
                    requested=joint["requested"], estimable=joint["estimable"], failed=joint["failed"],
                    physical_group_identity_sha256=joint["physical_group_identity_sha256"], draw_multiplicity_sha256=joint["draw_multiplicity_sha256"])
                common_effects.append(record)
                target = S(f"{orbit}_joint_original_common_{size}km_SEALED.npz")
                target.parent.mkdir(parents=True, exist_ok=True); target.parent.chmod(0o700)
                np.savez_compressed(target, points=joint["points"], paired_draws=joint["draws"], difference_draws=joint["difference_draws"], valid=joint["valid"])
                target.chmod(0o600)
                est = result["status"]=="ESTIMABLE"
                public_precision_rows.append(precision_row(r, kind="joint_common_minus_original", variant=f"joint_{size}km",
                    group_km=size, cells=len(common), blocks=len(common_stats.labels), groups=joint["groups"], requested=1000, estimable=result["estimable"],
                    t_se=result["SE"][0] if est else None, t_width=result["q975"][0]-result["q025"][0] if est else None,
                    m_se=result["SE"][1] if est else None, m_width=result["q975"][1]-result["q025"][1] if est else None,
                    pairing="verified same physical multiplicities; missing common blocks zero", method="new 95% percentile joint block bootstrap"))
            p = old_precision[(old_precision.pass_id.eq(f"phoenix:{orbit}")) & old_precision.variant.eq("common_cells_all11")]
            if len(p)!=1: raise ValueError("Common precision identity ambiguous")
            public_precision_rows.append(from_existing(r, p.iloc[0], "archived_common_estimate"))
            del original_stats, common_stats, common_model, common
        # Linear endpoint replacement cancels context/intercepts in delta; still
        # use the archived prediction function on explicitly supported rows.
        if ref_support["status"] == "SUPPORTED":
            fit = PooledFit(source_coef, model["bootstrap_coefficients"], {}, names, model["block_labels"], model["block_x_means"], model["block_y_means"], list(OUTCOMES))
            predicted = fit.prediction_difference(frame.loc[ref_mask], reference["f0"], reference["f1"])["delta"]
            assert_close(predicted, source_coef[0]*.1, "Frozen linear reference prediction does not recover canopy difference", 1e-8)
            assert_close(-predicted[0], float(q.iloc[0].cooling_K_per_10pp), "Released temperature contrast does not reconcile", 1e-8)
            for size, variant in ((1, "paired_primary"), (8, "spatial_8km")):
                diag_model = model if size==1 else reader.model(model_path(r, variant))
                assert_close(diag_model["coefficients"], source_coef, "Spatial grouping changed archived point model", 1e-8)
                if not np.array_equal(diag_model["predictor_names"], model["predictor_names"]): raise ValueError("Paired scale model order changed")
                b = diag_model["bootstrap_coefficients"][:, 0]*.1
                result, values = paired_scale(predicted[0], predicted[1], b, reference["reference_K"], reference["reference_emissivity"])
                result.update(city=city, orbit=orbit, date=r["date"], source_run_id=r["run_id"], group_km=size, reference_support=ref_support)
                paired_scales.append(result)
                if values is not None:
                    target = S(f"{city}_{orbit}_paired_scale_{size}km_SEALED.npz")
                    np.savez_compressed(target, paired_CE_draws=values, paired_T_minus_equivalent_draws=values[:, 0]-values[:, 1]); target.chmod(0o600)
                if size==1:
                    for dt in (-10, 0, 10):
                        for de in (-.01, 0, .01):
                            alt, _ = paired_scale(predicted[0], predicted[1], b, reference["reference_K"]+dt, min(.999, reference["reference_emissivity"]+de))
                            alt.update(city=city, orbit=orbit, date=r["date"], temperature_offset_K=dt, emissivity_offset=de)
                            ref_sens.append(alt)
        else:
            for size in (1, 8): paired_scales.append(dict(city=city, orbit=orbit, date=r["date"], group_km=size, status="NOT_SUPPORTED_NO_REFERENCE_BLOCKS"))
        # Original and available-support shifts retain separate uncertainty; the
        # row/sample evidence does not justify matched difference intervals.
        for variant in ("paired_primary", "spatial_8km"):
            if variant=="spatial_8km":
                existing = table # Original released long table has 8km rows elsewhere.
                raw_table = reader.csv("deliverables/Results_Review_2023_v6_2_20261004/pass_results_long.csv")
                a = raw_table[(raw_table.city.eq(city)) & raw_table.orbit.eq(orbit) & raw_table.variant.eq("spatial_uncertainty_8km")].iloc[0]
                public_precision_rows.append(precision_row(r, kind="original_spatial_precision", variant="spatial_8km", group_km=8,
                    cells=int(a.n_cells), blocks=int(a.n_blocks), groups=int(a.resampling_groups), requested=int(a.bootstrap_requested), estimable=int(a.bootstrap_estimable),
                    t_se=float(a.spatial_SE_K_per_10pp), t_width=float(a.interval_width_K_per_10pp), m_se=float(a.flux_spatial_SE_W_m2_per_10pp), m_width=float(a.flux_interval_width_W_m2_per_10pp),
                    pairing="constituent precision only", method="existing 95% whole-spatial-group percentile bootstrap"))
            else:
                p = primary_precision[r["run_id"]]
                p = p[(p.pass_id.eq(f"{city}:{orbit}")) & p.variant.eq(variant)]
                if len(p)!=1: raise ValueError("Primary precision identity ambiguous")
                public_precision_rows.append(from_existing(r, p.iloc[0], "original_spatial_precision"))
        if city=="phoenix":
            for dx, dy in SHIFTS:
                variant = f"registration_dx{dx}_dy{dy}"
                path = f"{OLD_SEALED}/{orbit}_{variant}_SEALED.npz" if "extension" in r["run_id"] else model_path(r, variant)
                shifted = reader.model(path)
                base_summary = summary(-source_coef[0]*.1, -model["bootstrap_coefficients"][:, 0]*.1)
                shifted_summary = summary(-shifted["coefficients"][0]*.1, -shifted["bootstrap_coefficients"][:, 0]*.1)
                available_effects.append(dict(orbit=orbit, date=r["date"], source_run_id=r["run_id"], variant=variant,
                    original=base_summary, shifted=shifted_summary, shifted_minus_original=(-.1*(shifted["coefficients"][0]-source_coef[0])).tolist(),
                    difference_interval_status="UNAVAILABLE_DIFFERING_OR_UNVERIFIED_SAMPLE; separate constituent intervals only"))
                source = old_precision if "extension" in r["run_id"] else primary_precision[r["run_id"]]
                p = source[(source.pass_id.eq(f"phoenix:{orbit}")) & source.variant.eq(variant)]
                if len(p)!=1: raise ValueError("Registration precision identity ambiguous")
                public_precision_rows.append(from_existing(r, p.iloc[0], "registration_available_support"))
        del frame, model
        gc.collect()
        print(json.dumps({"stage": "pass_reviewed", "city": city, "orbit": orbit, "predictor_cells": int(q.iloc[0].n_cells), "new_effects": "SEALED"}), flush=True)
    # Existing matched-support registration arrays have the same block/order and
    # RNG sampling algorithm; validate every paired summary against saved records.
    archived_matched = reader.json(OLD_SEALED+"/registration_matched_support_comparisons_SEALED.json")
    matched = {(str(r["orbit"]), r["variant"]): r for r in archived_matched}
    fixed_effects, fixed_validations = [], []
    for r in added:
        orbit = str(r["orbit"])
        rebuild = reader.json(f"{OLD}/{orbit}_baseline_rebuild_validation.json")
        if rebuild["status"]!="EXACT_MATCH": raise ValueError("Archived baseline identity not validated")
        base = reader.model(f"{OLD_SEALED}/{orbit}_registration_fixed_support_dx0_dy0_SEALED.npz")
        support = old_registration[old_registration.orbit.eq(orbit)]
        if len(support)!=5 or support.common_across_alignments_cells.nunique()!=1: raise ValueError("Fixed-support ledger mismatch")
        base_p = old_precision[(old_precision.pass_id.eq(f"phoenix:{orbit}")) & old_precision.variant.eq("registration_fixed_support_dx0_dy0")].iloc[0]
        public_precision_rows.append(from_existing(r, base_p, "registration_fixed_support_estimate"))
        for dx, dy in SHIFTS:
            variant = f"registration_fixed_support_dx{dx}_dy{dy}"
            b = reader.model(f"{OLD_SEALED}/{orbit}_{variant}_SEALED.npz")
            p = old_precision[(old_precision.pass_id.eq(f"phoenix:{orbit}")) & old_precision.variant.eq(variant)].iloc[0]
            if not np.array_equal(base["block_labels"], b["block_labels"]) or not np.array_equal(base["predictor_names"], b["predictor_names"]): raise ValueError("Fixed registration physical/design order mismatch")
            if int(base_p.seed)!=int(p.seed) or int(base_p.n_cells)!=int(p.n_cells) or int(p.n_cells)!=int(support.iloc[0].common_across_alignments_cells): raise ValueError("Fixed registration RNG/sample mismatch")
            assert_close(base["block_y_means"], b["block_y_means"], "Fixed-support paired outcomes differ", 0)
            point = -.1*(b["coefficients"][0]-base["coefficients"][0])
            draws = -.1*(b["bootstrap_coefficients"][:, 0]-base["bootstrap_coefficients"][:, 0])
            result = summary(point, draws)
            stored = matched[(orbit, variant)]
            assert_close(result["point"], -np.asarray(stored["signed_difference_per_10pp"]), "Archived paired registration point does not reconcile")
            assert_close(result["SE"], stored["paired_difference_SE_per_10pp"], "Archived paired registration SE does not reconcile")
            q = np.asarray(stored["paired_difference_q025_q975_per_10pp"])
            assert_close(result["q025"], -q[1], "Archived paired interval lower sign/order does not reconcile")
            assert_close(result["q975"], -q[0], "Archived paired interval upper sign/order does not reconcile")
            if result["estimable"]!=stored["paired_estimable_draws"]: raise ValueError("Paired registration draw count mismatch")
            fixed_effects.append(dict(orbit=orbit, date=r["date"], variant=variant, source_run_id=r["run_id"], **result))
            fixed_validations.append(dict(orbit=orbit, variant=variant, blocks_and_predictors_identical=True, matched_outcomes=True,
                seed_algorithm_and_draw_order_verified=True, cells=int(p.n_cells), estimable_draws=result["estimable"], archived_signed_interval_reconciled=True))
            public_precision_rows.append(from_existing(r, p, "registration_fixed_support_estimate"))
            public_precision_rows.append(precision_row(r, kind="paired_fixed_support_difference", variant=variant,
                group_km=1, cells=int(p.n_cells), blocks=int(p.n_blocks), groups=int(p.resampling_groups), requested=1000, estimable=result["estimable"],
                t_se=result["SE"][0], t_width=result["q975"][0]-result["q025"][0], m_se=result["SE"][1], m_width=result["q975"][1]-result["q025"][1],
                pairing="validated archived physical blocks, sample, algorithm and draw summaries", method="existing paired whole-block percentile difference bootstrap"))
    if len(fixed_validations)!=24 or old_validation["comparison_count"]!=24: raise ValueError("Incomplete fixed registration review")
    # Write new effects/plots only beneath the guarded sealed root.
    for filename, value in (("common_footprint_review_SEALED.json", common_effects), ("fixed_registration_review_SEALED.json", fixed_effects),
                            ("available_registration_review_SEALED.json", available_effects), ("paired_scale_review_SEALED.json", paired_scales),
                            ("reference_sensitivity_review_SEALED.json", ref_sens)):
        write_sealed_json(ROOT, RUN, filename, value)
    public_precision_rows = [public_precision(r) for r in public_precision_rows]
    residuals = []
    for city in ("phoenix", "atlanta"):
        path = f"outputs/v6_2/scientific/pooled_pilot_20260919_{city}/residual_spatial_diagnostics.csv"
        records = reader.csv(path).to_dict("records")
        for row in records: row["source"] = path
        residuals.extend(records)
    table_inputs = {
        "spatial_precision_review.csv": public_precision_rows,
        "canopy_context_distributions.csv": distributions,
        "footprint_and_reference_support.csv": footprint_rows,
        "inherited_residual_spatial_diagnostics.csv": residuals,
    }
    write_public_json("public_table_matrices.json", {name: {"headers": list(rows[0]), "rows": [[row[k] for k in rows[0]] for row in rows]} for name, rows in table_inputs.items()})
    write_public_json("predictor_CDF.json", cdf)
    write_public_json("validation.json", dict(status="INTERNAL_COMPUTATION_AND_SUPPORT_COMPLETE_EFFECTS_SEALED",
        Phoenix_passes=11, Atlanta_passes=5, year=2023, common_cells=len(ids), common_area_km2=len(ids)*.0049,
        common_identity_sha256=identity_hash(ids), union_native_cells=len(union_points), original_and_common_point_recoveries=len(support_validation),
        joint_difference_configurations=len(common_effects), joint_requested=sum(r["requested"] for r in common_effects),
        joint_estimable=sum(r["estimable"] for r in common_effects), joint_failed=sum(r["failed"] for r in common_effects),
        fixed_registration_pairs=len(fixed_validations), available_support_points=len(available_effects),
        paired_scale_configurations=len(paired_scales), paired_scale_estimable=sum(r["status"]=="ESTIMABLE" for r in paired_scales),
        reference_sensitivity_configurations=len(ref_sens),
        new_mean_model_specifications=0, targeted_reconstructions=22, raw_thermal_raster_reads=0, empirical_time_comparisons=0,
        displayed_new_effects=False, agreement_ruling=False, scale_tolerance=None,
        common_checks=support_validation, fixed_registration_checks=fixed_validations,
        public_table_rows={name: len(rows) for name, rows in table_inputs.items()},
        retained_predictor_and_coordinate_values_identical_across_common_passes=True))
    write_public_json("access_record.json", dict(created_utc=datetime.now(timezone.utc).isoformat(),
        user_authority=freeze["authority"], accesses=reader.access, public_outputs="nonthermal support, provenance and precision only",
        new_effects="sealed files; not opened in preview or sent to user", time_contrast_files_opened=[],
        absolute_thermal_access="cached original T/M/emissivity for paired point/draw reconstruction and fixed-reference diagnostics; no raw raster",
        raw_inputs_and_old_models_modified=False))
    xy = np.asarray(list(union_points.values()))
    common_xy = shared_predictors[["x", "y"]].to_numpy()
    plot_public_support(ROOT, RUN, phoenix, footprint_rows, cdf, xy, common_xy)
    plot_sealed_reviews(ROOT, RUN, common_effects, fixed_effects, available_effects, paired_scales, ref_sens)
    write_public_json("plot_qa_metadata.json", dict(public_figures="rendered; visual inspection pending", sealed_figures="rendered without image emission; visual inspection deferred to authorized release"))
    print(json.dumps({"stage": "internal_review_complete", "common_cells": len(ids), "joint_configurations": len(common_effects),
        "joint_estimable": sum(r["estimable"] for r in common_effects), "fixed_registration_pairs": len(fixed_validations),
        "paired_scale_estimable": sum(r["status"]=="ESTIMABLE" for r in paired_scales), "new_effects": "SEALED_USER_REQUEST"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    freeze_inputs() if args.freeze else run()
