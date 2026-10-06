"""Offline, gate-ineligible packaging for illustrative Guide Steps 2 and 3.

This module is deliberately separate from the canonical Task-1 pipeline.  It reads
only existing catalogue metadata, an existing geometry-progress checkpoint, and
the already produced catalogue-ceiling template.  It never imports or opens an
ECOSTRESS thermal/LST layer and never performs network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from statistics import NormalDist
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


STATUS = "STOP_USER_SKIPPED_D0047_GEOMETRY_710_OF_911"
BANNER = "ILLUSTRATIVE — SYNTHETIC DATA — NOT A STUDY RESULT"
ASCII_BANNER = "ILLUSTRATIVE - SYNTHETIC DATA - NOT A STUDY RESULT"
EXPECTED_CATALOGUE_ROWS = 2_968
EXPECTED_DAYTIME_CEILING = 1_055
EXPECTED_GEOMETRY_CANDIDATES = 911
EXPECTED_GEOMETRY_EVALUATED = 710
EXPECTED_GEOMETRY_UNEVALUATED = 201
DEFAULT_SEED = 20260805
STEP3_DATA_ORIGIN = "synthetic_catalogue_ceiling_demonstration"


@dataclass(frozen=True)
class IllustrativeRoots:
    """Resolved output locations for the quarantined continuation."""

    repo_root: Path
    output_root: Path
    figures_root: Path

    @classmethod
    def defaults(cls, repo_root: Path) -> "IllustrativeRoots":
        repo_root = Path(repo_root).resolve()
        return cls(
            repo_root=repo_root,
            output_root=(
                repo_root / "data/processed/v2/illustrative_only/steps02_13"
            ),
            figures_root=(repo_root / "figures/v2/illustrative_only/steps02_13"),
        )


def status_contract() -> dict[str, Any]:
    """Return a new copy of the noncanonical status contract."""

    return {
        "status": STATUS,
        "scientific_gate_eligible": False,
        "task1_gate": "STOP",
        "task2_activated": False,
        "lst_opened": False,
        "thermal_opened": False,
        "holdout_status": "UNSELECTED",
        "record_2026_opened": False,
    }


def sha256_file(path: Path) -> str:
    """Hash a local file without following any external resource."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_file(path: Path, *, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError(f"{label} is missing or empty: {path}")
    return path


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def _finish_figure(
    fig: plt.Figure,
    path: Path,
    *,
    subtitle: str,
    synthetic: bool,
) -> Path:
    """Apply the mandatory visible disclosure and save deterministic metadata."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.suptitle(BANNER, color="#a40000", fontsize=12, fontweight="bold", y=0.995)
    origin = (
        "Synthetic demonstration only"
        if synthetic
        else "Empirical catalogue metadata, partial/incomplete; not a usable-pass result"
    )
    fig.text(
        0.5,
        0.007,
        f"{subtitle} | {origin} | canonical gate remains STOP",
        ha="center",
        va="bottom",
        fontsize=7,
        color="#5a0000",
    )
    fig.tight_layout(rect=(0.02, 0.035, 0.98, 0.94))
    fig.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        metadata={
            "Title": path.stem,
            "Description": BANNER,
            "Subject": origin,
            "Creator": "urban_cooling_v2 illustrative-only offline runner",
        },
    )
    plt.close(fig)
    if path.stat().st_size <= 0:
        raise RuntimeError(f"generated an empty figure: {path}")
    return path


def _source_paths(repo_root: Path) -> dict[str, Path]:
    catalogue = repo_root / "data/processed/v2/task1/step2_catalogue_audit/tables"
    return {
        "scene_metadata": catalogue / "step2_scene_catalogue_metadata_only.csv",
        "t2_1": catalogue / "T2.1_daytime_catalogue_ceiling_counts.csv",
        "t2_2": catalogue / "T2.2_attrition_not_evaluated.csv",
        "t2_3": catalogue / "T2.3_scene_metadata_dictionary.csv",
        "step3_template": catalogue / "step3_catalogue_ceiling_template.csv",
        # D0050 is a historical, user-stopped 710/911 snapshot.  The live
        # geometry checkpoint later advanced to 911/911 and must not rewrite
        # or invalidate that quarantined illustrative package.
        "geometry_snapshot": repo_root / "docs/v2/D0050_GEOMETRY_SNAPSHOT.json",
    }


def _load_sources(repo_root: Path) -> tuple[dict[str, Path], dict[str, Any]]:
    paths = {
        key: _require_file(path, label=key)
        for key, path in _source_paths(repo_root).items()
    }
    scene = pd.read_csv(paths["scene_metadata"], low_memory=False)
    template = pd.read_csv(paths["step3_template"])
    snapshot = json.loads(paths["geometry_snapshot"].read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise RuntimeError("D0050 geometry snapshot must be a JSON object")
    if snapshot.get("decision_id") != "D0050":
        raise RuntimeError("Historical geometry snapshot is not bound to D0050")
    completed = int(snapshot.get("d0047_geometry_evaluated_at_user_skip", -1))
    facts = {
        "catalogue_metadata_rows": int(len(scene)),
        "daytime_catalogue_ceiling_passes": int(len(template)),
        "d0047_geometry_candidates": EXPECTED_GEOMETRY_CANDIDATES,
        "d0047_geometry_evaluated_at_user_skip": int(completed),
        "d0047_geometry_unevaluated_at_user_skip": int(
            EXPECTED_GEOMETRY_CANDIDATES - completed
        ),
        "checkpoint_updated_utc": snapshot.get("checkpoint_updated_utc"),
    }
    expected = {
        "catalogue_metadata_rows": EXPECTED_CATALOGUE_ROWS,
        "daytime_catalogue_ceiling_passes": EXPECTED_DAYTIME_CEILING,
        "d0047_geometry_candidates": EXPECTED_GEOMETRY_CANDIDATES,
        "d0047_geometry_evaluated_at_user_skip": EXPECTED_GEOMETRY_EVALUATED,
        "d0047_geometry_unevaluated_at_user_skip": EXPECTED_GEOMETRY_UNEVALUATED,
    }
    mismatches = {
        key: {"observed": facts[key], "expected": value}
        for key, value in expected.items()
        if facts[key] != value
    }
    if mismatches:
        raise RuntimeError(f"illustrative snapshot facts changed: {mismatches}")
    return paths, {"scene": scene, "template": template, "facts": facts}


def _metadata_figures(
    scene: pd.DataFrame,
    template: pd.DataFrame,
    facts: dict[str, Any],
    figures_root: Path,
    *,
    seed: int,
) -> list[Path]:
    artifacts: list[Path] = []
    daytime = scene.loc[scene["daytime"].fillna(False).astype(bool)].copy()
    cities = sorted(str(value) for value in daytime["city"].dropna().unique())

    fig, axes = plt.subplots(len(cities), 1, figsize=(8.5, 9.5), sharex=True)
    axes = np.atleast_1d(axes)
    for axis, city in zip(axes, cities, strict=True):
        values = pd.to_numeric(
            daytime.loc[daytime["city"] == city, "local_solar_time_hours"],
            errors="coerce",
        ).dropna()
        axis.hist(values, bins=np.arange(10, 18.01, 0.5), color="#4472c4")
        for boundary in (10, 12, 14, 16, 18):
            axis.axvline(boundary, color="#222222", linewidth=0.7)
        axis.set_ylabel(city.replace("_", " "))
        axis.text(
            0.99,
            0.82,
            f"catalogue-daytime n={len(values)}",
            transform=axis.transAxes,
            ha="right",
            fontsize=8,
        )
    axes[-1].set_xlabel("Local solar time (hours)")
    artifacts.append(
        _finish_figure(
            fig,
            figures_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_F2.1_local_solar_time_catalogue_ceiling.png",
            subtitle="F2.1 catalogue-daytime ceiling, not usable-pass counts",
            synthetic=False,
        )
    )

    detail = daytime.loc[
        daytime["time_stratum"].notna(), ["city", "year", "time_stratum", "scene_key"]
    ].drop_duplicates()
    city_year = detail.pivot_table(
        index="city", columns="year", values="scene_key", aggfunc="count", fill_value=0
    )
    city_stratum = detail.pivot_table(
        index="city",
        columns="time_stratum",
        values="scene_key",
        aggfunc="count",
        fill_value=0,
    ).reindex(columns=["10-12", "12-14", "14-16", "16-18"], fill_value=0)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for axis, frame, title in (
        (axes[0], city_year, "City × year"),
        (axes[1], city_stratum, "City × time stratum"),
    ):
        image = axis.imshow(frame.to_numpy(dtype=float), cmap="Blues", aspect="auto")
        axis.set_title(title)
        axis.set_yticks(range(len(frame.index)), [x.replace("_", " ") for x in frame.index])
        axis.set_xticks(range(len(frame.columns)), [str(x) for x in frame.columns], rotation=45)
        for row in range(frame.shape[0]):
            for col in range(frame.shape[1]):
                axis.text(col, row, str(int(frame.iloc[row, col])), ha="center", va="center", fontsize=7)
        fig.colorbar(image, ax=axis, shrink=0.75)
    artifacts.append(
        _finish_figure(
            fig,
            figures_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_F2.2_daytime_catalogue_ceiling_heatmaps.png",
            subtitle="F2.2 catalogue ceiling only; quality/cloud stages incomplete",
            synthetic=False,
        )
    )

    labels = [
        "catalogue\nmetadata rows",
        "daytime\npass ceiling",
        "D0047 geometry\ncandidates",
        "geometry\nevaluated",
        "geometry\nunevaluated",
    ]
    values = [
        facts["catalogue_metadata_rows"],
        facts["daytime_catalogue_ceiling_passes"],
        facts["d0047_geometry_candidates"],
        facts["d0047_geometry_evaluated_at_user_skip"],
        facts["d0047_geometry_unevaluated_at_user_skip"],
    ]
    fig, axis = plt.subplots(figsize=(10, 5.2))
    bars = axis.bar(labels, values, color=["#4472c4", "#5b9bd5", "#70ad47", "#ffc000", "#c00000"])
    axis.bar_label(bars, padding=3)
    axis.set_ylabel("Count (units differ; bars are not an attrition denominator)")
    axis.set_title("F2.3 partial inventory facts at the user-directed stop")
    axis.text(
        0.5,
        0.88,
        "No cloud-complete or usable-pass total exists; 201/911 candidates were not evaluated.",
        transform=axis.transAxes,
        ha="center",
        color="#a40000",
        fontweight="bold",
    )
    artifacts.append(
        _finish_figure(
            fig,
            figures_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_F2.3_incomplete_attrition_snapshot.png",
            subtitle="F2.3 deliberately incomplete; unlike units are not treated as a waterfall",
            synthetic=False,
        )
    )

    modes = sorted(str(value) for value in daytime["retrieval_band_mode"].dropna().unique())
    palette = {mode: plt.cm.Set2(i / max(1, len(modes) - 1)) for i, mode in enumerate(modes)}
    fig, axis = plt.subplots(figsize=(12, 5.8))
    city_index = {city: index for index, city in enumerate(cities)}
    rng = np.random.default_rng(seed)
    for mode in modes:
        subset = daytime.loc[daytime["retrieval_band_mode"].astype(str) == mode]
        dates = pd.to_datetime(subset["acquisition_utc"], utc=True, errors="coerce")
        valid = dates.notna()
        subset = subset.loc[valid]
        dates = dates.loc[valid]
        y = np.asarray(
            [city_index[str(value)] for value in subset["city"]], dtype=float
        )
        y += rng.uniform(-0.08, 0.08, len(y))
        axis.scatter(dates, y, s=8, alpha=0.65, label=mode, color=palette[mode])
    axis.set_yticks(range(len(cities)), [city.replace("_", " ") for city in cities])
    axis.set_xlabel("Acquisition date")
    axis.set_title("F2.4 catalogue-daytime pass-date strip")
    axis.legend(title="retrieval mode", fontsize=8)
    artifacts.append(
        _finish_figure(
            fig,
            figures_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_F2.4_pass_date_strip_catalogue_ceiling.png",
            subtitle="F2.4 catalogue ceiling; no cloud-complete usable-pass interpretation",
            synthetic=False,
        )
    )

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharex=True, sharey=True)
    sample = template.copy()
    demand = pd.to_numeric(sample["demand_pct"], errors="coerce")
    dryness = pd.to_numeric(sample["dryness_pct"], errors="coerce")
    axes[0].scatter(demand, dryness, s=8, alpha=0.35, color="#7030a0")
    synthetic_mask = np.arange(len(sample)) % 3 != 0
    axes[1].scatter(
        demand[synthetic_mask],
        dryness[synthetic_mask],
        s=8,
        alpha=0.35,
        color="#ed7d31",
    )
    for axis, title in zip(
        axes,
        ("Catalogue-ceiling template", "Synthetic retained subset demonstration"),
        strict=True,
    ):
        axis.set_title(title)
        axis.set_xlabel("Demand percentile")
        axis.set_ylabel("Antecedent-dryness percentile")
        for boundary in (1 / 3, 2 / 3):
            axis.axvline(boundary, color="#555555", linewidth=0.7)
            axis.axhline(boundary, color="#555555", linewidth=0.7)
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1)
    artifacts.append(
        _finish_figure(
            fig,
            figures_root
            / "synthetic_downstream/step02/"
            "ILLUSTRATIVE_F2.5_definitive_conditions_not_available.png",
            subtitle="F2.5 substitute is synthetic; definitive acquisition-time result does not exist",
            synthetic=True,
        )
    )
    return artifacts


def _normal_power(effect: float, n_passes: float, sigma: float = 8.0) -> float:
    normal = NormalDist()
    critical = normal.inv_cdf(0.975)
    noncentrality = effect * np.sqrt(n_passes) / sigma
    return float(
        1.0
        - normal.cdf(critical - noncentrality)
        + normal.cdf(-critical - noncentrality)
    )


def _step3_demonstration(
    output_root: Path,
    figures_root: Path,
    *,
    seed: int,
) -> tuple[list[Path], list[dict[str, Any]]]:
    artifacts: list[Path] = []
    origins: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    pass_counts = np.array([25, 50, 100, 200, 400, 800, 1055], dtype=int)
    effect_sizes = np.array([0.75, 1.50, 2.25], dtype=float)

    power_rows = [
        {
            "n_passes": int(n),
            "effect_size_k": float(effect),
            "demonstration_power": _normal_power(effect, int(n)),
            "origin": "synthetic_catalogue_ceiling_demonstration",
            "data_origin": STEP3_DATA_ORIGIN,
            "scientific_gate_eligible": False,
        }
        for n in pass_counts
        for effect in effect_sizes
    ]
    power = pd.DataFrame(power_rows)
    path = _write_csv(
        output_root
        / "synthetic_downstream/step03/ILLUSTRATIVE_step3_power_demonstration.csv",
        power,
    )
    artifacts.append(path)

    fig, axis = plt.subplots(figsize=(8.5, 5.2))
    for effect in effect_sizes:
        subset = power.loc[power["effect_size_k"] == effect]
        axis.plot(subset["n_passes"], subset["demonstration_power"], marker="o", label=f"{effect:.2f} K")
    axis.axhline(0.80, color="#555555", linestyle="--", label="80% target")
    axis.axvline(EXPECTED_DAYTIME_CEILING, color="#a40000", linestyle=":", label="1,055 catalogue ceiling")
    axis.set(xlabel="Synthetic pass count", ylabel="Demonstration detection probability", ylim=(0, 1.02))
    axis.legend()
    f3_1_path = _finish_figure(
            fig,
            figures_root / "synthetic_downstream/step03/ILLUSTRATIVE_F3.1_power_curves.png",
            subtitle="F3.1 uses a catalogue ceiling, not observed usable passes",
            synthetic=True,
    )
    artifacts.append(f3_1_path)

    transition_rows: list[dict[str, Any]] = []
    for n in pass_counts:
        replicates = 400
        events = rng.binomial(1, 0.05 + 0.01 * np.exp(-n / 100.0), replicates)
        transition_rows.append(
            {
                "n_passes": int(n),
                "replicates": replicates,
                "false_positive_rate": float(events.mean()),
                "nominal_alpha": 0.05,
                "origin": "synthetic_smooth_truth",
                "data_origin": STEP3_DATA_ORIGIN,
                "scientific_gate_eligible": False,
            }
        )
    transition = pd.DataFrame(transition_rows)
    path = _write_csv(
        output_root
        / "synthetic_downstream/step03/ILLUSTRATIVE_transition_false_positive.csv",
        transition,
    )
    artifacts.append(path)
    fig, axis = plt.subplots(figsize=(8.5, 5.2))
    axis.plot(transition["n_passes"], transition["false_positive_rate"], marker="o")
    axis.axhline(0.05, color="#a40000", linestyle="--", label="nominal 0.05")
    axis.set(xlabel="Synthetic pass count", ylabel="Transition false-positive rate", ylim=(0, 0.15))
    axis.legend()
    f3_2_path = _finish_figure(
            fig,
            figures_root / "synthetic_downstream/step03/ILLUSTRATIVE_F3.2_transition_false_positive.png",
            subtitle="F3.2 smooth-truth synthetic demonstration",
            synthetic=True,
    )
    artifacts.append(f3_2_path)

    breakpoints = np.clip(rng.normal(3.0, 1.15, 1200), 0.4, 5.8)
    breakpoint_frame = pd.DataFrame(
        {
            "estimated_breakpoint_kpa": breakpoints,
            "truth": "no_breakpoint_smooth_curve",
            "origin": "synthetic",
            "data_origin": STEP3_DATA_ORIGIN,
            "scientific_gate_eligible": False,
        }
    )
    path = _write_csv(
        output_root
        / "synthetic_downstream/step03/ILLUSTRATIVE_spurious_breakpoints.csv",
        breakpoint_frame,
    )
    artifacts.append(path)
    fig, axis = plt.subplots(figsize=(8.5, 5.2))
    axis.hist(breakpoints, bins=30, color="#7030a0", alpha=0.8)
    axis.set(xlabel="Estimated breakpoint (kPa) under no-breakpoint truth", ylabel="Synthetic replicates")
    f3_3_path = _finish_figure(
            fig,
            figures_root / "synthetic_downstream/step03/ILLUSTRATIVE_F3.3_spurious_breakpoints.png",
            subtitle="F3.3 fake breakpoint distribution under smooth synthetic truth",
            synthetic=True,
    )
    artifacts.append(f3_3_path)

    true_effect = 1.50
    recovery_rows: list[dict[str, Any]] = []
    for n in pass_counts:
        se = 8.0 / np.sqrt(n)
        estimates = true_effect + rng.normal(0.0, se, 600)
        mean = float(estimates.mean())
        recovery_rows.append(
            {
                "n_passes": int(n),
                "true_effect_k": true_effect,
                "mean_estimate_k": mean,
                "ci_low_k": mean - 1.96 * float(estimates.std(ddof=1)) / np.sqrt(len(estimates)),
                "ci_high_k": mean + 1.96 * float(estimates.std(ddof=1)) / np.sqrt(len(estimates)),
                "origin": "synthetic",
                "data_origin": STEP3_DATA_ORIGIN,
                "scientific_gate_eligible": False,
            }
        )
    recovery = pd.DataFrame(recovery_rows)
    path = _write_csv(
        output_root / "synthetic_downstream/step03/ILLUSTRATIVE_coefficient_recovery.csv",
        recovery,
    )
    artifacts.append(path)
    fig, axis = plt.subplots(figsize=(8.5, 5.2))
    axis.errorbar(
        recovery["n_passes"],
        recovery["mean_estimate_k"],
        yerr=[
            recovery["mean_estimate_k"] - recovery["ci_low_k"],
            recovery["ci_high_k"] - recovery["mean_estimate_k"],
        ],
        marker="o",
        capsize=4,
    )
    axis.axhline(true_effect, color="#a40000", linestyle="--", label="synthetic truth")
    axis.set(xlabel="Synthetic pass count", ylabel="Recovered interaction coefficient (K)")
    axis.legend()
    f3_4_path = _finish_figure(
            fig,
            figures_root / "synthetic_downstream/step03/ILLUSTRATIVE_F3.4_coefficient_recovery.png",
            subtitle="F3.4 synthetic known-parameter recovery",
            synthetic=True,
    )
    artifacts.append(f3_4_path)

    coverage_rows: list[dict[str, Any]] = []
    for n in pass_counts:
        block = np.clip(0.95 + rng.normal(0, 0.008), 0, 1)
        naive = np.clip(0.76 + 0.03 * np.log10(n / 25) + rng.normal(0, 0.008), 0, 1)
        coverage_rows.extend(
            [
                {
                    "n_passes": int(n),
                    "interval_method": "pass_block",
                    "coverage": float(block),
                    "origin": "synthetic",
                    "data_origin": STEP3_DATA_ORIGIN,
                    "scientific_gate_eligible": False,
                },
                {
                    "n_passes": int(n),
                    "interval_method": "naive_row",
                    "coverage": float(naive),
                    "origin": "synthetic",
                    "data_origin": STEP3_DATA_ORIGIN,
                    "scientific_gate_eligible": False,
                },
            ]
        )
    coverage = pd.DataFrame(coverage_rows)
    path = _write_csv(
        output_root / "synthetic_downstream/step03/ILLUSTRATIVE_bootstrap_coverage.csv",
        coverage,
    )
    artifacts.append(path)
    fig, axis = plt.subplots(figsize=(8.5, 5.2))
    for method, subset in coverage.groupby("interval_method", sort=True):
        axis.plot(subset["n_passes"], subset["coverage"], marker="o", label=method)
    axis.axhline(0.95, color="#a40000", linestyle="--", label="nominal 0.95")
    axis.set(xlabel="Synthetic pass count", ylabel="Interval coverage", ylim=(0.65, 1.0))
    axis.legend()
    f3_5_path = _finish_figure(
            fig,
            figures_root / "synthetic_downstream/step03/ILLUSTRATIVE_F3.5_bootstrap_coverage.png",
            subtitle="F3.5 synthetic pass-block versus naive-row coverage",
            synthetic=True,
    )
    artifacts.append(f3_5_path)

    model_rows = []
    for model, minimum in (
        ("two_way_demand_x_dryness", 200),
        ("time_stratum_specific_two_way", 400),
        ("three_way_time_x_demand_x_dryness", 800),
    ):
        detectable = 1.96 * 8.0 / np.sqrt(EXPECTED_DAYTIME_CEILING)
        model_rows.append(
            {
                "data_origin": STEP3_DATA_ORIGIN,
                "model": model,
                "illustrative_minimum_passes": minimum,
                "catalogue_daytime_ceiling": EXPECTED_DAYTIME_CEILING,
                "illustrative_detectable_effect_k_at_ceiling": detectable,
                "illustrative_ceiling_comparison": "ABOVE_DEMONSTRATION_MINIMUM",
                "canonical_support_verdict": "NOT_ESTIMABLE_INCOMPLETE_STEP2",
                "task1_gate": "STOP",
                "scientific_gate_eligible": False,
            }
        )
    t3_1 = pd.DataFrame(model_rows)
    t3_path = _write_csv(
        output_root
        / "synthetic_downstream/step03/ILLUSTRATIVE_T3.1_model_support_catalogue_ceiling.csv",
        t3_1,
    )
    artifacts.append(t3_path)

    for artifact_id, artifact_path, description in (
        ("F3.1", f3_1_path, "Synthetic interaction-power demonstration"),
        ("F3.2", f3_2_path, "Synthetic transition false-positive demonstration"),
        ("F3.3", f3_3_path, "Synthetic spurious-breakpoint demonstration"),
        ("F3.4", f3_4_path, "Synthetic coefficient-recovery demonstration"),
        ("F3.5", f3_5_path, "Synthetic interval-coverage demonstration"),
        ("T3.1", t3_path, "Catalogue-ceiling model-support demonstration; not a support verdict"),
    ):
        origins.append(
            {
                "artifact_id": artifact_id,
                "path": str(artifact_path),
                "origin_class": "synthetic_downstream",
                "description": description,
                "scientific_gate_eligible": False,
                "synthetic": True,
                "completeness": "illustrative_only",
            }
        )
    return artifacts, origins


def write_steps02_03(
    *,
    output_root: Path,
    figures_root: Path,
    repo_root: Path,
    seed: int = DEFAULT_SEED,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write Steps 2–3 artifacts into the noncanonical quarantine."""

    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve()
    figures_root = Path(figures_root).resolve()
    contract = status_contract() if status is None else dict(status)
    if contract != status_contract():
        raise ValueError("illustrative Steps 2–3 require the exact STOP status contract")

    for root in (output_root, figures_root):
        (root / "empirical_nonthermal").mkdir(parents=True, exist_ok=True)
        (root / "synthetic_downstream").mkdir(parents=True, exist_ok=True)

    source_paths, loaded = _load_sources(repo_root)
    scene = loaded["scene"]
    template = loaded["template"]
    facts = loaded["facts"]
    artifacts: list[Path] = []
    origins: list[dict[str, Any]] = []

    facts_record = {
        **contract,
        **facts,
        "completeness": "PARTIAL_USER_STOPPED",
        "usable_pass_count_available": False,
        "cloud_complete": False,
        "claim_limit": (
            "The 1,055 count is a catalogue-daytime ceiling. The 710/911 geometry "
            "checkpoint is incomplete; 201 candidates were not evaluated."
        ),
        "source_sha256": {
            key: sha256_file(path) for key, path in sorted(source_paths.items())
        },
    }
    facts_path = _write_json(
        output_root
        / "empirical_nonthermal/step02/EMPIRICAL_PARTIAL_step02_snapshot_facts.json",
        facts_record,
    )
    artifacts.append(facts_path)

    table_specs = (
        (
            "T2.1",
            source_paths["t2_1"],
            output_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_T2.1_daytime_catalogue_ceiling_counts.csv",
            "Real catalogue-daytime ceiling counts; not usable-pass counts",
        ),
        (
            "T2.2",
            source_paths["t2_2"],
            output_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_T2.2_attrition_not_evaluated.csv",
            "Real partial attrition with unevaluated downstream stages",
        ),
        (
            "T2.3",
            source_paths["t2_3"],
            output_root
            / "empirical_nonthermal/step02/"
            "EMPIRICAL_PARTIAL_T2.3_scene_metadata_dictionary.csv",
            "Real catalogue metadata dictionary",
        ),
    )
    for artifact_id, source, destination, description in table_specs:
        frame = pd.read_csv(source, low_memory=False)
        frame["data_origin"] = "empirical_nonthermal_partial"
        frame["illustrative_package_status"] = STATUS
        frame["scientific_gate_eligible"] = False
        artifacts.append(_write_csv(destination, frame))
        origins.append(
            {
                "artifact_id": artifact_id,
                "path": str(destination),
                "origin_class": "empirical_nonthermal_partial",
                "description": description,
                "source_path": str(source),
                "source_sha256": sha256_file(source),
                "scientific_gate_eligible": False,
                "synthetic": False,
                "completeness": "partial_or_catalogue_ceiling",
            }
        )

    figures = _metadata_figures(scene, template, facts, figures_root, seed=seed)
    artifacts.extend(figures)
    for artifact_id, path, synthetic, description in (
        ("F2.1", figures[0], False, "Real catalogue-daytime solar-time distribution"),
        ("F2.2", figures[1], False, "Real catalogue-daytime ceiling heatmaps"),
        ("F2.3", figures[2], False, "Real but incomplete checkpoint inventory facts"),
        ("F2.4", figures[3], False, "Real catalogue-daytime pass-date strip"),
        ("F2.5", figures[4], True, "Synthetic substitute; definitive pass-date result unavailable"),
    ):
        origins.append(
            {
                "artifact_id": artifact_id,
                "path": str(path),
                "origin_class": (
                    "synthetic_downstream" if synthetic else "empirical_nonthermal_partial"
                ),
                "description": description,
                "scientific_gate_eligible": False,
                "synthetic": synthetic,
                "completeness": "illustrative_only" if synthetic else "partial",
            }
        )

    step3_artifacts, step3_origins = _step3_demonstration(
        output_root,
        figures_root,
        seed=seed,
    )
    artifacts.extend(step3_artifacts)
    origins.extend(step3_origins)
    return {
        "writer": "write_steps02_03",
        "status": contract,
        "artifacts": [str(path) for path in artifacts],
        "origins": origins,
        "facts": facts_record,
    }


__all__ = [
    "ASCII_BANNER",
    "BANNER",
    "DEFAULT_SEED",
    "IllustrativeRoots",
    "STATUS",
    "sha256_file",
    "status_contract",
    "write_steps02_03",
]
