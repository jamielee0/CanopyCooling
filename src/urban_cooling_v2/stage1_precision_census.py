#!/usr/bin/env python3
"""Pure analysis helpers for the v6.2 D1d Stage-1 precision census.

The real-data runner keeps point estimates behind the sealed-output boundary.
This module returns the coefficient separately from the open diagnostic record
so callers cannot accidentally place it in the public table.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

import numpy as np


REQUIRED_LAYERS = ("LST", "QC", "cloud", "water", "height")
MIN_VALID_CELLS = 60
MIN_CANOPY_SPAN = 0.20
MIN_CELLS_PER_QUADRANT = 8
MAX_QUADRANT_INFORMATION_SHARE = 0.75
RELIABILITIES = (0.30, 0.50, 0.70)
DETECTION_CONSTANT = 7.85
EQUIVALENCE_CONSTANT = 6.18
PLANNING_DESIGN_EFFECT = 2.5
LATENT_DETECTION_EFFECT = 0.10
LATENT_EQUIVALENCE_BOUND = 0.05


_LSTE_RE = re.compile(
    r"^ECOv(?P<version>\d{3})_L2T_LSTE_(?P<orbit>\d+)_(?P<scene>\d+)_"
    r"(?P<tile>[0-9A-Z]+)_(?P<instant>\d{8}T\d{6})_(?P<build>\d+)_"
    r"(?P<revision>\d+)_(?P<layer>LST|QC|cloud|water|height)\.tif$"
)


@dataclass(frozen=True)
class NativeBundle:
    orbit: int
    scene: int
    tile: str
    instant: str
    build: int
    revision: int
    layers: Mapping[str, Path]

    @property
    def pass_id(self) -> str:
        return f"phoenix:{self.orbit}"


def discover_latest_complete_bundles(
    raw_dir: str | Path,
    selected_orbits: Iterable[int],
) -> list[NativeBundle]:
    """Choose the latest complete five-layer bundle per orbit/scene/tile."""

    wanted = {int(value) for value in selected_orbits}
    grouped: dict[tuple[int, int, str, str, int, int], dict[str, Path]] = {}
    for path in Path(raw_dir).glob("ECOv*_L2T_LSTE_*.tif"):
        match = _LSTE_RE.match(path.name)
        if not match:
            continue
        fields = match.groupdict()
        orbit = int(fields["orbit"])
        if orbit not in wanted:
            continue
        key = (
            orbit,
            int(fields["scene"]),
            fields["tile"],
            fields["instant"],
            int(fields["build"]),
            int(fields["revision"]),
        )
        grouped.setdefault(key, {})[fields["layer"]] = path

    complete: list[NativeBundle] = []
    by_scene_tile: dict[tuple[int, int, str], list[tuple[tuple[int, ...], dict[str, Path]]]] = {}
    for key, layers in grouped.items():
        if set(layers) != set(REQUIRED_LAYERS):
            continue
        orbit, scene, tile, instant, build, revision = key
        by_scene_tile.setdefault((orbit, scene, tile), []).append(
            ((build, revision, int(instant.replace("T", ""))), layers)
        )

    for (orbit, scene, tile), candidates in sorted(by_scene_tile.items()):
        _, layers = max(candidates, key=lambda item: item[0])
        parsed = _LSTE_RE.match(layers["LST"].name)
        assert parsed is not None
        fields = parsed.groupdict()
        complete.append(
            NativeBundle(
                orbit=orbit,
                scene=scene,
                tile=tile,
                instant=fields["instant"],
                build=int(fields["build"]),
                revision=int(fields["revision"]),
                layers=dict(layers),
            )
        )

    found = {bundle.orbit for bundle in complete}
    missing = sorted(wanted.difference(found))
    if missing:
        raise ValueError(f"Selected orbits lack a complete native bundle: {missing}")
    return sorted(
        complete,
        key=lambda item: (item.orbit, item.scene, item.tile, item.instant),
    )


def build_quality_mask(
    lst_k: np.ndarray,
    qc: np.ndarray,
    cloud: np.ndarray,
    water: np.ndarray,
) -> np.ndarray:
    """Frozen Collection-2 finite, QA 00/01, clear-land mask."""

    mandatory = np.asarray(qc, dtype=np.uint16) & np.uint16(0b11)
    return (
        np.isfinite(np.asarray(lst_k, dtype=float))
        & (mandatory <= 1)
        & (np.asarray(cloud) == 0)
        & (np.asarray(water) == 0)
    )


def merge_scene_arrays(
    scenes: Sequence[Mapping[str, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Merge one tile across ordered scenes under the frozen cloudy-wins rule.

    Returns LST, height, and a boolean validity array. Later items in ``scenes``
    supply a remaining valid value, while an observed cloud or water flag in any
    scene invalidates the cell.
    """

    if not scenes:
        raise ValueError("At least one scene is required")
    shape = np.asarray(scenes[0]["LST"]).shape
    out_lst = np.full(shape, np.nan, dtype=float)
    out_height = np.full(shape, np.nan, dtype=float)
    any_bad = np.zeros(shape, dtype=bool)
    any_valid = np.zeros(shape, dtype=bool)
    for scene in scenes:
        if any(np.asarray(scene[layer]).shape != shape for layer in REQUIRED_LAYERS):
            raise ValueError("Scene layers do not share one native grid")
        lst = np.asarray(scene["LST"], dtype=float)
        present = np.isfinite(lst)
        cloud = np.asarray(scene["cloud"])
        water = np.asarray(scene["water"])
        any_bad |= present & ((cloud != 0) | (water != 0))
        valid = build_quality_mask(lst, scene["QC"], cloud, water)
        out_lst[valid] = lst[valid]
        height = np.asarray(scene["height"], dtype=float)
        out_height[valid] = height[valid]
        any_valid |= valid
    valid = any_valid & ~any_bad & np.isfinite(out_height)
    out_lst[~valid] = np.nan
    out_height[~valid] = np.nan
    return out_lst, out_height, valid


def _fit_ols(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if len(y) <= x.shape[1]:
        return None
    beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if int(rank) != x.shape[1] or not np.all(np.isfinite(beta)):
        return None
    fitted = x @ beta
    residual = y - fitted
    xtx_inv = np.linalg.pinv(x.T @ x, rcond=1e-12)
    hat = np.einsum("ij,jk,ik->i", x, xtx_inv, x)
    return beta, residual, hat


def cardinal_morans_i(
    residual: np.ndarray,
    x_coord: np.ndarray,
    y_coord: np.ndarray,
    spacing_m: float = 70.0,
) -> tuple[float, int]:
    """Global Moran's I using undirected east/north native-cell pairs."""

    residual = np.asarray(residual, dtype=float)
    x_coord = np.asarray(x_coord, dtype=float)
    y_coord = np.asarray(y_coord, dtype=float)
    finite = np.isfinite(residual) & np.isfinite(x_coord) & np.isfinite(y_coord)
    residual = residual[finite]
    x_coord = x_coord[finite]
    y_coord = y_coord[finite]
    n = len(residual)
    if n < 3:
        return math.nan, 0
    centered = residual - residual.mean()
    denominator = float(centered @ centered)
    if denominator <= 0:
        return math.nan, 0
    keys = {
        (int(round(x / spacing_m)), int(round(y / spacing_m))): index
        for index, (x, y) in enumerate(zip(x_coord, y_coord))
    }
    products: list[float] = []
    for (gx, gy), index in keys.items():
        for neighbor in ((gx + 1, gy), (gx, gy + 1)):
            other = keys.get(neighbor)
            if other is not None:
                products.append(float(centered[index] * centered[other]))
    edges = len(products)
    if edges == 0:
        return math.nan, 0
    # S0 is twice the number of undirected edges; the numerator is likewise doubled.
    value = n * float(np.sum(products)) / (edges * denominator)
    return float(value), edges


def _failure_row(
    *,
    city: str,
    block_id: str,
    pass_id: str,
    n: int,
    span: float,
    mean_canopy: float,
    reason: str,
) -> dict[str, object]:
    return {
        "city": city,
        "block_id": block_id,
        "pass_id": pass_id,
        "valid_cell_count": int(n),
        "canopy_span_p10_p90": float(span),
        "mean_canopy_fraction": float(mean_canopy),
        "spatially_robust_se_K_per_10pp": None,
        "max_hat_leverage": None,
        "leverage_threshold": None,
        "high_leverage_flag": None,
        "residual_morans_i": None,
        "cardinal_neighbor_pairs": 0,
        "context_terms_retained": 0,
        "spatial_replicates_successful": 0,
        "max_quadrant_canopy_information_share": None,
        "estimability_flag": False,
        "convergence_flag": False,
        "design_stability_flag": False,
        "failure_reason": reason,
    }


def fit_block_pass(
    *,
    city: str,
    block_id: str,
    pass_id: str,
    lst_k: np.ndarray,
    canopy_fraction: np.ndarray,
    context: Mapping[str, np.ndarray],
    x_coord: np.ndarray,
    y_coord: np.ndarray,
    block_origin_x: float,
    block_origin_y: float,
) -> tuple[dict[str, object], float | None]:
    """Fit one block-pass and return open diagnostics plus a separate slope."""

    names = list(context)
    arrays = [
        np.asarray(lst_k, dtype=float),
        np.asarray(canopy_fraction, dtype=float),
        np.asarray(x_coord, dtype=float),
        np.asarray(y_coord, dtype=float),
        *[np.asarray(context[name], dtype=float) for name in names],
    ]
    finite = np.logical_and.reduce([np.isfinite(value) for value in arrays])
    y = arrays[0][finite]
    canopy = arrays[1][finite]
    xs = arrays[2][finite]
    ys = arrays[3][finite]
    covariates = [value[finite] for value in arrays[4:]]
    n = len(y)
    span = float(np.quantile(canopy, 0.90) - np.quantile(canopy, 0.10)) if n else math.nan
    mean_canopy = float(np.mean(canopy)) if n else math.nan
    if n < MIN_VALID_CELLS:
        return _failure_row(
            city=city,
            block_id=block_id,
            pass_id=pass_id,
            n=n,
            span=span,
            mean_canopy=mean_canopy,
            reason="valid_cell_count_below_60",
        ), None
    if span < MIN_CANOPY_SPAN:
        return _failure_row(
            city=city,
            block_id=block_id,
            pass_id=pass_id,
            n=n,
            span=span,
            mean_canopy=mean_canopy,
            reason="canopy_span_below_0_20",
        ), None

    columns = [np.ones(n, dtype=float), canopy - canopy.mean()]
    retained_context = 0
    for values in covariates:
        centered = values - values.mean()
        scale = float(np.std(centered, ddof=0))
        if scale > 1e-10:
            columns.append(centered / scale)
            retained_context += 1
    design = np.column_stack(columns)
    full = _fit_ols(design, y)
    if full is None:
        return _failure_row(
            city=city,
            block_id=block_id,
            pass_id=pass_id,
            n=n,
            span=span,
            mean_canopy=mean_canopy,
            reason="full_design_not_estimable",
        ), None
    beta, residual, hat = full
    slope = float(beta[1])

    east = xs >= (float(block_origin_x) + 500.0)
    north = ys >= (float(block_origin_y) + 500.0)
    quadrants = east.astype(np.int8) + 2 * north.astype(np.int8)
    counts = np.bincount(quadrants, minlength=4)
    if np.any(counts < MIN_CELLS_PER_QUADRANT):
        row = _failure_row(
            city=city,
            block_id=block_id,
            pass_id=pass_id,
            n=n,
            span=span,
            mean_canopy=mean_canopy,
            reason="spatial_quadrant_below_8_cells",
        )
        row["max_hat_leverage"] = float(np.max(hat))
        row["context_terms_retained"] = retained_context
        return row, None

    replicate_slopes: list[float] = []
    for quadrant in range(4):
        keep = quadrants != quadrant
        result = _fit_ols(design[keep], y[keep])
        if result is not None:
            replicate_slopes.append(float(result[0][1]))
    if len(replicate_slopes) != 4:
        row = _failure_row(
            city=city,
            block_id=block_id,
            pass_id=pass_id,
            n=n,
            span=span,
            mean_canopy=mean_canopy,
            reason="jackknife_replicate_not_estimable",
        )
        row["max_hat_leverage"] = float(np.max(hat))
        row["context_terms_retained"] = retained_context
        row["spatial_replicates_successful"] = len(replicate_slopes)
        return row, None

    replicate = np.asarray(replicate_slopes, dtype=float)
    replicate_mean = float(np.mean(replicate))
    se_fraction = math.sqrt(3.0 / 4.0 * float(np.sum((replicate - replicate_mean) ** 2)))
    se_10pp = 0.10 * se_fraction

    nuisance = np.column_stack([design[:, 0], *[design[:, i] for i in range(2, design.shape[1])]])
    canopy_centered = design[:, 1]
    nuisance_beta, _, _, _ = np.linalg.lstsq(nuisance, canopy_centered, rcond=None)
    canopy_residual = canopy_centered - nuisance @ nuisance_beta
    information = np.array(
        [float(np.sum(canopy_residual[quadrants == value] ** 2)) for value in range(4)]
    )
    total_information = float(np.sum(information))
    max_information_share = (
        float(np.max(information) / total_information) if total_information > 0 else math.nan
    )
    max_hat = float(np.max(hat))
    leverage_threshold = max(0.25, 2.0 * design.shape[1] / n)
    high_leverage = max_hat > leverage_threshold
    moran, neighbor_pairs = cardinal_morans_i(residual, xs, ys)
    stable = (
        np.isfinite(se_10pp)
        and se_10pp > 0
        and np.isfinite(max_information_share)
        and max_information_share <= MAX_QUADRANT_INFORMATION_SHARE
        and not high_leverage
    )
    row = {
        "city": city,
        "block_id": block_id,
        "pass_id": pass_id,
        "valid_cell_count": int(n),
        "canopy_span_p10_p90": span,
        "mean_canopy_fraction": mean_canopy,
        "spatially_robust_se_K_per_10pp": float(se_10pp),
        "max_hat_leverage": max_hat,
        "leverage_threshold": float(leverage_threshold),
        "high_leverage_flag": bool(high_leverage),
        "residual_morans_i": None if not np.isfinite(moran) else float(moran),
        "cardinal_neighbor_pairs": int(neighbor_pairs),
        "context_terms_retained": int(retained_context),
        "spatial_replicates_successful": 4,
        "max_quadrant_canopy_information_share": max_information_share,
        "estimability_flag": True,
        "convergence_flag": True,
        "design_stability_flag": bool(stable),
        "failure_reason": "",
    }
    return row, slope


def required_count(sigma_s: float, reliability: float, criterion: str) -> int:
    """Closed-form planning count with square-root attenuation."""

    if not (sigma_s > 0 and 0 < reliability <= 1):
        raise ValueError("sigma_s and reliability must be positive")
    if criterion == "detection":
        constant = DETECTION_CONSTANT
        target = LATENT_DETECTION_EFFECT * math.sqrt(reliability)
    elif criterion == "equivalence":
        constant = EQUIVALENCE_CONSTANT
        target = LATENT_EQUIVALENCE_BOUND * math.sqrt(reliability)
    else:
        raise ValueError(f"Unknown criterion: {criterion}")
    return int(math.ceil(constant * PLANNING_DESIGN_EFFECT * sigma_s**2 / target**2))


def build_power_rows(
    standard_errors: Sequence[float],
    d1b_rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, float]]:
    values = np.asarray(standard_errors, dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        raise ValueError("No finite positive Stage-1 standard errors")
    summaries = {
        "p25": float(np.quantile(values, 0.25)),
        "median": float(np.quantile(values, 0.50)),
        "p75": float(np.quantile(values, 0.75)),
    }
    rows: list[dict[str, object]] = []
    for item in d1b_rows:
        available = int(
            math.floor(
                float(item["block_passes"])
                * float(item["largest_connected_component_share"])
            )
        )
        for summary_name, sigma_s in summaries.items():
            for reliability in RELIABILITIES:
                for criterion in ("detection", "equivalence"):
                    rows.append(
                        {
                            "city": item["city"],
                            "season_window": item["season_window"],
                            "view_zenith_set_deg": int(item["view_zenith_set_deg"]),
                            "se_summary": summary_name,
                            "observed_stage1_se_K_per_10pp": sigma_s,
                            "reliability": reliability,
                            "criterion": criterion,
                            "attenuated_target_K_per_10pp": (
                                (LATENT_DETECTION_EFFECT if criterion == "detection" else LATENT_EQUIVALENCE_BOUND)
                                * math.sqrt(reliability)
                            ),
                            "required_connected_block_passes": required_count(
                                sigma_s, reliability, criterion
                            ),
                            "available_connected_block_passes_D1b": available,
                        }
                    )
    return rows, summaries


def free_check_ruling(
    power_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    optimistic = [
        row
        for row in power_rows
        if row["se_summary"] == "p25" and float(row["reliability"]) == 0.70
    ]
    if not optimistic:
        raise ValueError("Optimistic p25/reliability-0.70 rows are missing")
    required = max(int(row["required_connected_block_passes"]) for row in optimistic)
    maxima: dict[str, int] = {}
    for row in optimistic:
        city = str(row["city"])
        maxima[city] = max(maxima.get(city, 0), int(row["available_connected_block_passes_D1b"]))
    stop = bool(maxima) and all(value < required for value in maxima.values())
    return {
        "optimistic_required_connected_block_passes": required,
        "available_connected_block_passes_max_by_city": maxima,
        "stop_before_gate_A": stop,
        "ruling": (
            "STOP_BEFORE_GATE_A_PRECISION_LOWER_BOUND_EXCEEDS_BOTH_CITIES"
            if stop
            else "DO_NOT_STOP_ON_D1D_PRECISION_PROCEED_TO_SUPERVISOR_REVIEW"
        ),
        "gate_A_authorized": False,
    }

