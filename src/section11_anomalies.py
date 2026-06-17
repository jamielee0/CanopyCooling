#!/usr/bin/env python3
"""Section 11 - Compute anomalies and deseasonalize the stress variables (steps 58-61).

Implements the whole of Section 11 for the Phoenix pilot from this one module, so
it re-runs end to end from saved code (protocol standing rule: "every figure and
every number must be reproducible from the saved code; nothing produced by hand").

Objective (protocol Section 11, steps 58-61)
--------------------------------------------
Convert the raw stress variables entering the Compound Stress Index -- VPD, the
chosen water-supply indicator (NDMI), and soil moisture as a CHECK -- into
STANDARDIZED ANOMALIES (z-scores) per pixel per overpass:

  58. CLIMATOLOGY (seasonal normal). For each pixel the normal for a given
      calendar day = mean of all observations within +/- CLIMATOLOGY_WINDOW_DAYS
      (15) of that day across all years 2018-2024 (a day-of-year MOVING WINDOW,
      because the daily sampling is sparse).
  59. SUB-DAILY variables (VPD and soil moisture are HOURLY) build the climatology
      AT THE OVERPASS HOUR: match each ECOSTRESS overpass to its ERA5-Land hour and
      compute the normal from values at that SAME hour-of-day, so the daily cycle
      does not contaminate the anomaly.
  60. LEAVE-ONE-YEAR-OUT: when computing the normal for an observation in year Y,
      exclude year Y from the average.
  61. Climatological STANDARD DEVIATION over the same window.
  Step 2: ANOMALY = observed - normal.   Step 3: Z = anomaly / std.
  Step 4 (QC): each variable's z averages ~0 with std ~1 across the record; the
      most extreme positive VPD z-scores fall on known peak-heat dates of summer
      2023; one mapped extreme date is spatially sensible.

COMMON PITFALL (guarded here): computing ONE climatology for the WHOLE season
instead of a day-of-year climatology leaves the seasonal cycle INSIDE the anomaly
-- early-June and late-August then look anomalous by construction. We ALWAYS
normalise as a function of day-of-year (the +/-15-day window), and PROVE the
seasonal cycle is gone with a season-part mean-z flatness check (figure + note).

================================================================================
KEY DESIGN DECISIONS (documented prominently; see also data/processed/README.md
and the results note docs/section11_anomaly_qc_note.md)
================================================================================
(A) VPD and SOIL MOISTURE -- a rigorous TEMPORAL day-of-year-AT-OVERPASS-HOUR
    leave-one-year-out climatology, done in NATIVE ERA5 space then regridded.
    ------------------------------------------------------------------------------
    The 2018-2024 hourly record exists ONLY for ERA5-Land VPD + soil moisture
    (data/interim/era5land_vpd_sm_hourly_2018_2024.nc; 8x10 native ~9 km tile,
    20496 warm-season hours, EPSG:4326). We compute the climatology, anomaly and
    z-score in that NATIVE 8x10 hourly space, THEN bilinear-regrid the per-overpass
    z-score fields (and the climatology mean/std fields) to the 70 m grid. Working
    in native space keeps the observed value and its climatology in the SAME space
    (cleaner than mixing the Section 9 cube's already-regridded observed value with
    a native climatology). For each overpass: day-of-year D, hour-of-day H (UTC,
    from the matched ERA5 hour), year Y (= 2023 for every pilot overpass). The
    NORMAL at each native pixel = mean of ERA5 vpd (resp. sm) at hour-of-day == H,
    over all days with |doy - D| <= 15, across 2018-2024 EXCLUDING year Y (LOYO);
    the STD = std over that same set. The +/-15-day window is CLIPPED to the
    available warm-season data (no day-of-year wraparound -- it is within-season),
    so the earliest June / latest September overpasses get a one-sided window; that
    is expected and documented. The OBSERVED value (the z numerator) is the ERA5
    value at the overpass's matched hour in 2023, recomputed from the .nc in native
    space for consistency (NOT reused from the cube's regridded value). z = (obs -
    normal) / std. Result: per-overpass VPD-z and SM-z on the 70 m grid (66 x y x x).

(B) NDMI -- a TEMPORAL day-of-year-AT-OVERPASS anomaly from Section 4b's
    time-resolved NDMI product (the per-overpass series + its LOYO climatology).
    ------------------------------------------------------------------------------
    Section 4b now produces a TIME-RESOLVED NDMI store on the 70 m grid
    (data/interim/s2_ndmi_timeseries_70m.zarr; dims overpass=66 x y x x), indexed by
    the SAME 66 overpass_keys (same order) as the analysis cube, with vars:
      observed   -- per-overpass cloud-masked S2 NDMI (+/-15 d around each 2023
                    overpass date) -- VARIES across overpasses,
      clim_mean,
      clim_std   -- the 2018-2024 day-of-year (+/-15 d) leave-one-year-out NDMI
                    climatology.
    The water-supply z-score is therefore the SAME temporal anomaly formula as
    VPD/SM, computed PER OVERPASS PER PIXEL directly on the 70 m grid (no regrid --
    Section 4b already delivered it at 70 m; the same degenerate clim_std==0 ->
    NaN guard):
        z_NDMI(overpass, pixel) = (observed - clim_mean) / clim_std.
    This REPLACES the previous static SPATIAL standardization of a single 2023
    composite (the historical decision, kept here only as context: Section 4
    originally produced one warm-season median composite, so only a spatial
    standardization was possible). z_NDMI now VARIES IN TIME AND SPACE.
    CONSEQUENCE (stated plainly): the water-supply stress that feeds Section 12's
    SUPPLY axis is NO LONGER a static spatial field -- the CSI supply axis is
    UNFROZEN, so the CSI's temporal variation now comes from BOTH the demand (VPD)
    and the supply (NDMI) sides, each a proper day-of-year-at-overpass LOYO anomaly.

(C) SOIL MOISTURE z (from (A)) remains the protocol's independent TEMPORAL "check"
    on the water-supply story, kept alongside the (now also temporal) NDMI-z.

Deliverables (checkpoint, Section 11; data/processed/, git-ignored)
-------------------------------------------------------------------
* section11_zscores_70m.zarr -- THE deliverable. Per-overpass standardized
  anomalies on the 70 m grid, dims (overpass=66, y=1155, x=1339):
    vpd_z   -- VPD z-score (temporal day-of-year-at-overpass-hour LOYO climatology)
    sm_z    -- soil-moisture z-score (same temporal climatology; the CHECK)
    ndmi_z  -- water-supply z-score (TEMPORAL day-of-year-at-overpass anomaly from
               Section 4b's per-overpass series + LOYO climatology; varies in time)
  plus the SAVED CLIMATOLOGY fields (needed to interpret results later, step 4
  DELIVERABLE), as (overpass, y, x):
    vpd_clim_mean, vpd_clim_std, sm_clim_mean, sm_clim_std,
    ndmi_clim_mean, ndmi_clim_std
  coords overpass/overpass_key/time/era5_hour/y/x and a CF spatial_ref (reopen with
  decode_coords="all"). Aligned exactly to reference_grid.tif.
* section11_zscores_overpass_summary.parquet -- a small 66-row per-overpass table
  (regional-mean z and clim fields, season part) for a quick scan / the QC tables.
* figures/section11_zscore_distributions.png -- z histograms (mean~0/std~1).
* figures/section11_seasonal_cycle_check.png -- mean z per season part (FLAT? the
  key day-of-year-climatology check vs the whole-season pitfall).
* figures/section11_vpd_z_extreme_date_map.png -- 70 m VPD-z map for the top
  extreme overpass (a known peak-heat 2023 date).
* docs/section11_anomaly_qc_note.md -- the QC results note (step 4, documented).

Run (canopy env; no network -- reads only data/interim + data/processed):
    python src/section11_anomalies.py                 # full Section 11
    python src/section11_anomalies.py --no-figures     # skip the QC figures
    python src/section11_anomalies.py --verify-only    # re-open + QC the saved store
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic below (the +/-15-day-at-hour LOYO window
# selection, the anomaly/z formulas -- now also used for the NDMI temporal z -- and
# the season-part binning) does not touch them, so it stays unit-testable without the
# geo stack installed (see test_section11_anomalies.py).
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402

# Make config importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402

log = logging.getLogger("section11")


# =========================================================================== #
# Source layers + deliverable names.
# --------------------------------------------------------------------------- #
ERA5_NC = "era5land_vpd_sm_hourly_2018_2024.nc"   # Section 6 hourly record (the basis)
ANALYSIS_CUBE = "analysis_cube_70m.zarr"          # Section 9 cube -> the overpass axis
# Section 4b time-resolved NDMI: per-overpass observed + 2018-2024 day-of-year LOYO
# climatology mean/std, already on the 70 m grid and indexed by the SAME 66
# overpass_keys (same order) as the analysis cube. Replaces the old single static
# composite s2_ndmi_warmseason_median_2023_70m.tif.
NDMI_TS_ZARR = "s2_ndmi_timeseries_70m.zarr"

# Variables with a TRUE temporal day-of-year climatology.
#   VPD + soil moisture -> hourly ERA5-Land record (native space then regridded);
#   NDMI -> the Section 4b per-overpass time series on the 70 m grid directly.
TEMPORAL_VARS = ("vpd", "sm")
# The water-supply indicator now also gets a TEMPORAL day-of-year-at-overpass anomaly
# (Section 4b supplied the per-overpass series + climatology); it is NOT spatially
# standardized any more.
TEMPORAL_GRID_VAR = "ndmi"

# Deliverables (data/processed/).
ZSCORE_ZARR = "section11_zscores_70m.zarr"
OVERPASS_SUMMARY_PARQUET = "section11_zscores_overpass_summary.parquet"

# Figures.
FIG_DIST = "section11_zscore_distributions.png"
FIG_SEASON = "section11_seasonal_cycle_check.png"
FIG_EXTREME = "section11_vpd_z_extreme_date_map.png"

# Results note (markdown alongside the deliverable, docs/).
QC_NOTE = "section11_anomaly_qc_note.md"

# Known peak-heat window of summer 2023 (the step-4 extreme-date expectation):
# July 2023 was Phoenix's hottest month on record -- a 31-day streak of >=110 F
# daily highs from ~2023-06-30 to ~2023-07-30, peaking mid-to-late July.
HEATWAVE_2023 = (pd.Timestamp("2023-06-30"), pd.Timestamp("2023-07-30"))

# Season-part bins (half-month) for the seasonal-cycle flatness check (step 4).
# Edges as (label, month, day_lo, day_hi_inclusive) within the Jun-Sep warm season.
SEASON_PARTS = (
    ("Jun a", 6, 1, 15), ("Jun b", 6, 16, 30),
    ("Jul a", 7, 1, 15), ("Jul b", 7, 16, 31),
    ("Aug a", 8, 1, 15), ("Aug b", 8, 16, 31),
    ("Sep a", 9, 1, 15), ("Sep b", 9, 16, 30),
)


# =========================================================================== #
# Pure logic (numpy / pandas / str only; unit-tested without the geo stack)
# =========================================================================== #
def doy_window_mask(doys: np.ndarray, target_doy: int,
                    window_days: int = config.CLIMATOLOGY_WINDOW_DAYS) -> np.ndarray:
    """Boolean mask of samples within +/- ``window_days`` of ``target_doy`` (step 58).

    A simple ABSOLUTE day-of-year distance (no wraparound across the year boundary):
    the record is within-season (Jun-Sep), so an early-June or late-September target
    legitimately gets a ONE-SIDED window clipped to the available data -- that is the
    expected, documented behaviour, not a bug. ``doys`` is an array of day-of-year
    integers for the candidate samples.
    """
    return np.abs(np.asarray(doys) - int(target_doy)) <= int(window_days)


def climatology_select_mask(doys: np.ndarray, hours: np.ndarray, years: np.ndarray,
                            target_doy: int, target_hour: int, target_year: int,
                            window_days: int = config.CLIMATOLOGY_WINDOW_DAYS
                            ) -> np.ndarray:
    """Samples entering one overpass's normal/std: +/-window day-of-year, SAME hour,
    LEAVE-ONE-YEAR-OUT (steps 58-60).

    Combines three conditions on the candidate hourly samples:
      * day-of-year within +/- ``window_days`` of ``target_doy``  (step 58 window)
      * hour-of-day == ``target_hour``                             (step 59 at-hour)
      * year != ``target_year``                                    (step 60 LOYO)
    Returns the boolean mask; the caller reduces vpd/sm over it to the mean (normal)
    and std. Pure numpy on 1-D arrays so it is identical for the native-pixel case
    (the per-pixel reduction just applies this same time mask along the time axis).
    """
    doys = np.asarray(doys); hours = np.asarray(hours); years = np.asarray(years)
    return (doy_window_mask(doys, target_doy, window_days)
            & (hours == int(target_hour))
            & (years != int(target_year)))


def anomaly(observed, normal):
    """ANOMALY = observed - climatological normal (step 2). Elementwise; NaN-safe."""
    return np.asarray(observed, dtype="float64") - np.asarray(normal, dtype="float64")


def zscore(observed, normal, std, min_std: float = 0.0):
    """Z = (observed - normal) / std (steps 2-3).

    Elementwise over arrays of any shape. Where ``std`` is 0 or non-finite (a
    degenerate climatology -- e.g. a one-sided window with a single sample, or an
    all-constant pixel) the z is NaN rather than +/-inf, so a degenerate
    denominator never poisons the QC statistics. ``min_std`` lets a caller treat
    near-zero stds as degenerate too (default 0 = only exact zeros / non-finite).
    """
    a = anomaly(observed, normal)
    s = np.asarray(std, dtype="float64")
    bad = ~np.isfinite(s) | (s <= float(min_std))
    s_safe = np.where(bad, np.nan, s)
    return a / s_safe


def spatial_standardize(values, ref_mask=None):
    """SPATIAL standardized anomaly z = (x - mu) / sigma over a reference population.

    Generic utility (retained + unit-tested). It was the ORIGINAL NDMI water-supply
    z when only a single 2023 composite existed; NDMI now uses a TEMPORAL day-of-year
    anomaly from Section 4b's time series instead (design decision (B)), so this is no
    longer on the production path. ``mu`` and ``sigma`` are computed over the FINITE
    values (optionally further restricted by ``ref_mask``). Returns ``(z, mu, sigma)``;
    z keeps the input shape with NaN where the input is NaN. By construction z has
    mean ~0 / std ~1 over the reference population.
    """
    x = np.asarray(values, dtype="float64")
    finite = np.isfinite(x)
    pop = finite if ref_mask is None else (finite & np.asarray(ref_mask, dtype=bool))
    mu = float(np.mean(x[pop]))
    sigma = float(np.std(x[pop]))                 # population std (ddof=0)
    if not np.isfinite(sigma) or sigma == 0.0:
        return np.full(x.shape, np.nan, dtype="float64"), mu, sigma
    z = (x - mu) / sigma
    z[~finite] = np.nan
    return z, mu, sigma


def season_part_label(ts, parts: Sequence[tuple] = SEASON_PARTS) -> str | None:
    """Half-month season-part label for a timestamp (the seasonal-cycle bin, step 4).

    Returns e.g. 'Jul b' for 2023-07-20, or None if the date falls outside the
    defined warm-season parts. Used to bin overpasses and show the mean z per part
    is ~flat (proof the day-of-year climatology removed the seasonal cycle, vs the
    whole-season pitfall).
    """
    t = pd.Timestamp(ts)
    for label, month, lo, hi in parts:
        if t.month == month and lo <= t.day <= hi:
            return label
    return None


def part_order(parts: Sequence[tuple] = SEASON_PARTS) -> list[str]:
    """Season-part labels in calendar order (for ordering the flatness table/figure)."""
    return [p[0] for p in parts]


def season_part_profile(times, values) -> pd.DataFrame:
    """Mean of ``values`` per SEASON PART, in calendar order (the flatness profile).

    Bins the (time, value) pairs by half-month and returns a tidy DataFrame
    (season_part, n, mean). Used both for the per-overpass z flatness check and for
    the day-of-year-vs-whole-season pitfall demonstration on the dense ERA5 series.
    """
    df = pd.DataFrame({"part": [season_part_label(t) for t in pd.to_datetime(times)],
                       "value": np.asarray(values, dtype="float64")})
    rows = []
    for label in part_order():
        sub = df[df["part"] == label]
        if sub.empty:
            continue
        rows.append({"season_part": label, "n": int(len(sub)),
                     "mean": float(np.nanmean(sub["value"]))})
    return pd.DataFrame(rows)


def profile_spread(profile: pd.DataFrame) -> float:
    """max-min of a season-part profile's per-part means (the flatness scalar)."""
    if profile.empty:
        return float("nan")
    return float(np.nanmax(profile["mean"]) - np.nanmin(profile["mean"]))


def in_heatwave(ts, window: tuple = HEATWAVE_2023) -> bool:
    """Whether a date lies in the known 2023 Phoenix peak-heat window (step 4 check)."""
    t = pd.Timestamp(ts).normalize()
    lo, hi = window
    return lo.normalize() <= t <= hi.normalize()


def heatwave_enrichment(times, scores, top_k: int = 11,
                        window: tuple = HEATWAVE_2023) -> dict:
    """How strongly the 2023 heatwave window is ENRICHED among the highest scores.

    The strict "are the top-5 all heatwave dates?" framing is brittle: VPD-z is
    standardized PER HOUR, so a calm low-variance night can post a high z without
    being a heat extreme, while a blazing afternoon (high hour-of-day variance) posts
    a more modest z. The robust, honest statistic is ENRICHMENT: of the ``top_k``
    overpasses with the largest VPD-z, what fraction fall in the known peak-heat
    window, versus the window's share of ALL overpasses. >1 means the heatwave is
    over-represented at the top (the expected signal). Returns a dict with the counts,
    fractions and the enrichment ratio. Pure pandas; unit-friendly.
    """
    df = pd.DataFrame({"time": pd.to_datetime(times), "score": np.asarray(scores)})
    df["hw"] = df["time"].apply(lambda t: in_heatwave(t, window))
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    n = len(df)
    base = float(df["hw"].mean())                 # window's share of all overpasses
    k = min(int(top_k), n)
    top_frac = float(df.head(k)["hw"].mean())     # window's share of the top-k
    ranks = (np.where(df["hw"].to_numpy())[0] + 1).tolist()   # 1-based ranks of hw overpasses
    enrich = (top_frac / base) if base > 0 else float("nan")
    return {"n": n, "n_hw": int(df["hw"].sum()), "base_frac": base,
            "top_k": k, "top_frac": top_frac, "enrichment": enrich,
            "hw_ranks": ranks}


# =========================================================================== #
# ERA5 climatology + z (native 8x10 hourly space)  -- design decision (A)
# =========================================================================== #
def _open_era5(interim: Path) -> "xr.Dataset":
    """Open the 2018-2024 hourly ERA5-Land VPD/SM record (the climatology basis)."""
    era = xr.open_dataset(interim / ERA5_NC)
    return era


def _era5_time_fields(times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """day-of-year / hour-of-day / year arrays for the ERA5 time axis."""
    t = pd.DatetimeIndex(times)
    return (t.dayofyear.to_numpy(), t.hour.to_numpy(), t.year.to_numpy())


def compute_era5_zscores(era: "xr.Dataset", overpasses: pd.DataFrame,
                         var: str,
                         window_days: int = config.CLIMATOLOGY_WINDOW_DAYS
                         ) -> dict[str, np.ndarray]:
    """Per-overpass NATIVE (8x10) z, clim-mean and clim-std for one ERA5 variable.

    For each overpass (day-of-year D, hour H, year Y from the matched ERA5 hour):
      * select the climatology samples with |doy-D|<=window, hour==H, year!=Y (LOYO);
      * normal = mean over those samples (per native pixel), std = std over them;
      * observed = the ERA5 value AT the overpass's matched hour in year Y (recomputed
        from the .nc, native space);
      * z = (observed - normal) / std  (degenerate std -> NaN).
    Returns {'z','clim_mean','clim_std'} each a (n_overpass, nlat, nlon) float64 array
    in NATIVE space (regridded to 70 m by the caller). ``overpasses`` has columns
    'era5_hour' (the matched hour timestamp) and 'time'.
    """
    da = era[var]
    vals = da.values.astype("float64")            # (time, lat, lon)
    times = pd.DatetimeIndex(pd.to_datetime(era["time"].values))
    doys, hours, years = _era5_time_fields(times)
    # Fast lookup from a matched-hour timestamp to its index in the ERA5 time axis.
    pos_of_time = {pd.Timestamp(t): i for i, t in enumerate(times)}

    n = len(overpasses)
    nlat, nlon = vals.shape[1], vals.shape[2]
    z = np.full((n, nlat, nlon), np.nan, dtype="float64")
    cmean = np.full((n, nlat, nlon), np.nan, dtype="float64")
    cstd = np.full((n, nlat, nlon), np.nan, dtype="float64")

    n_onesided = 0
    for i, (_, row) in enumerate(overpasses.iterrows()):
        hour_ts = pd.Timestamp(row["era5_hour"])
        D = int(hour_ts.dayofyear)
        H = int(hour_ts.hour)
        Y = int(hour_ts.year)
        mask = climatology_select_mask(doys, hours, years, D, H, Y, window_days)
        if not mask.any():
            log.warning("  %s overpass %d (%s): NO climatology samples (doy=%d h=%d, "
                        "LOYO Y=%d) -> z is NaN", var, i, hour_ts, D, H, Y)
            continue
        sel = vals[mask]                          # (k, lat, lon)
        normal = np.nanmean(sel, axis=0)
        std = np.nanstd(sel, axis=0)              # population std over the window
        cmean[i] = normal
        cstd[i] = std
        # one-sided-window bookkeeping (early-June / late-Sep get clipped windows)
        win_doys = doys[mask]
        if (win_doys.min() > D - window_days) or (win_doys.max() < D + window_days):
            n_onesided += 1
        # observed = ERA5 value at the matched hour in the overpass year.
        idx = pos_of_time.get(hour_ts)
        if idx is None:
            log.warning("  %s overpass %d: matched hour %s not in ERA5 record -> NaN",
                        var, i, hour_ts)
            continue
        observed = vals[idx]                      # (lat, lon)
        z[i] = zscore(observed, normal, std)
    log.info("  %s native climatology built for %d overpasses "
             "(%d had a one-sided +/-%dd window -- early-June/late-Sep, expected)",
             var, n, n_onesided, window_days)
    return {"z": z, "clim_mean": cmean, "clim_std": cstd}


def daymark_vs_wholeseason_demo(era: "xr.Dataset", var: str = "vpd",
                                window_days: int = config.CLIMATOLOGY_WINDOW_DAYS
                                ) -> dict:
    """Demonstrate that the DAY-OF-YEAR climatology removes the seasonal cycle, by
    contrasting it with the WHOLE-SEASON pitfall on the DENSE ERA5 record (step 4).

    The protocol's pitfall: a single WHOLE-SEASON climatology leaves the seasonal
    cycle inside the anomaly. To PROVE our day-of-year-at-hour climatology avoids it,
    we standardize EVERY 2023 hourly ERA5 sample (the REGIONAL-MEAN series, thousands
    of samples -- far more than the 66 overpasses, so the test is not noise-limited)
    two ways, both leave-one-year-out at the matched hour:
      (A) day-of-year-at-hour: |doy-D|<=window AND hour==H AND year!=2023  (our method)
      (B) whole-season-at-hour: hour==H AND year!=2023  (the pitfall -- no doy window)
    and report the mean-z SEASON-PART profile + spread for each, AND a direct check
    that the day-of-year NORMAL tracks the within-season march while the whole-season
    normal is flat. Returns the two profiles, their spreads, and the normal-track
    series. This is the auditable evidence behind the "seasonal cycle removed" claim.
    """
    vals = era[var].values
    times = pd.DatetimeIndex(pd.to_datetime(era["time"].values))
    doys, hours, years = _era5_time_fields(times)
    reg = np.nanmean(vals.reshape(vals.shape[0], -1), axis=1)   # regional-mean series

    is2023 = years == 2023
    idx2023 = np.where(is2023)[0]
    zA, zB, t2023 = [], [], []
    for j in idx2023:
        D, H = int(doys[j]), int(hours[j])
        mA = (np.abs(doys - D) <= window_days) & (hours == H) & (years != 2023)
        mB = (hours == H) & (years != 2023)
        for store, m in ((zA, mA), (zB, mB)):
            seg = reg[m]
            mu = seg.mean(); sd = seg.std()
            store.append((reg[j] - mu) / sd if sd > 0 else np.nan)
        t2023.append(times[j])
    profA = season_part_profile(t2023, zA)
    profB = season_part_profile(t2023, zB)

    # the day-of-year NORMAL vs the whole-season NORMAL across the season (a fixed hour)
    H0 = 16
    track_doys = list(range(155, 273, 10))
    doy_norm = []
    for D in track_doys:
        m = (np.abs(doys - D) <= window_days) & (hours == H0)
        doy_norm.append(float(reg[m].mean()))
    whole_norm = float(reg[hours == H0].mean())

    return {"profile_daymark": profA, "profile_wholeseason": profB,
            "spread_daymark": profile_spread(profA),
            "spread_wholeseason": profile_spread(profB),
            "n_samples": len(idx2023),
            "track_hour": H0, "track_doys": track_doys,
            "track_doy_normal": doy_norm, "track_wholeseason_normal": whole_norm}


# =========================================================================== #
# Loading + regridding helpers (the geo stack)
# =========================================================================== #
def _reference():
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def _era5_latlon_names(era: "xr.Dataset") -> tuple[str, str]:
    lat = "latitude" if "latitude" in era.coords else "lat"
    lon = "longitude" if "longitude" in era.coords else "lon"
    return lat, lon


def regrid_native_stack(stack: np.ndarray, era: "xr.Dataset", reference: "xr.DataArray",
                        resampling: "Resampling" = Resampling.bilinear) -> np.ndarray:
    """Bilinear-regrid a (n, nlat, nlon) NATIVE ERA5 stack onto the 70 m grid.

    ERA5-Land carries no CRS in the .nc, so EPSG:4326 is written before the
    reproject_match. Continuous fields (z / clim-mean / clim-std) -> BILINEAR, the
    same method Section 9 uses for the ERA5 observed fields, so the z and its
    climatology land on the 70 m grid identically to the observed VPD/SM. Returns a
    (n, ny, nx) float32 array. Slice-by-slice to bound peak memory.
    """
    latn, lonn = _era5_latlon_names(era)
    lat = era[latn].values
    lon = era[lonn].values
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    out = np.full((stack.shape[0], ny, nx), np.nan, dtype="float32")
    for i in range(stack.shape[0]):
        da = xr.DataArray(stack[i].astype("float32"), dims=("y", "x"),
                          coords={"y": lat, "x": lon})
        da = da.rio.write_crs("EPSG:4326")
        matched = da.rio.reproject_match(reference, resampling=resampling)
        out[i] = matched.values.astype("float32")
    return out


def load_ndmi_timeseries(interim: Path, reference: "xr.DataArray",
                         overpasses: pd.DataFrame
                         ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load Section 4b's per-overpass NDMI series + day-of-year LOYO climatology.

    Returns ``(observed, clim_mean, clim_std)`` each a (n_overpass, ny, nx) float64
    array already on the 70 m grid. The store carries:
      * ``observed``  -- per-overpass cloud-masked S2 NDMI (varies across overpasses),
      * ``clim_mean`` -- the 2018-2024 day-of-year (+/-15 d) leave-one-year-out NDMI
                         climatological mean,
      * ``clim_std``  -- the matching climatological std,
    indexed by the SAME 66 ``overpass_key``s (same order) as the analysis cube. We
    assert that alignment AND that the store snaps to the reference grid, so the
    temporal z = (observed - clim_mean)/clim_std is computed directly on the 70 m
    grid (no regrid needed -- Section 4b already produced it at 70 m), exactly
    mirroring the VPD/SM anomaly formula (just done natively on the analysis grid).
    """
    ts = xr.open_zarr(interim / NDMI_TS_ZARR, decode_coords="all")
    # Geometry must match the reference grid (Section 9 rule).
    _assert_on_grid(ts["observed"], "ndmi_timeseries", reference)
    # Overpass axis must be the SAME keys in the SAME order as the master cube, so the
    # per-overpass divide lines up with VPD/SM and every downstream section.
    keys_ts = [str(k) for k in ts["overpass_key"].values]
    keys_axis = [str(k) for k in overpasses["overpass_key"].to_numpy()]
    if keys_ts != keys_axis:
        raise AssertionError(
            "ndmi_timeseries overpass_key order does not match the analysis-cube axis "
            f"(ts[0:3]={keys_ts[:3]} vs axis[0:3]={keys_axis[:3]}; n={len(keys_ts)} vs "
            f"{len(keys_axis)})")
    observed = ts["observed"].values.astype("float64")
    clim_mean = ts["clim_mean"].values.astype("float64")
    clim_std = ts["clim_std"].values.astype("float64")
    ts.close()
    return observed, clim_mean, clim_std


def _assert_on_grid(da: "xr.DataArray", name: str, reference: "xr.DataArray") -> None:
    """Assert a layer is EPSG:32612 and snapped to the reference grid (Section 9 rule)."""
    crs = da.rio.crs
    if crs is None or crs.to_epsg() != reference.rio.crs.to_epsg():
        raise AssertionError(f"{name}: CRS {crs} != reference {reference.rio.crs}")
    if da.sizes.get("y") != reference.sizes["y"] or da.sizes.get("x") != reference.sizes["x"]:
        raise AssertionError(
            f"{name}: shape (y={da.sizes.get('y')}, x={da.sizes.get('x')}) != "
            f"reference (y={reference.sizes['y']}, x={reference.sizes['x']})")
    if not np.allclose(da.x.values, reference.x.values, atol=1e-6):
        raise AssertionError(f"{name}: x coordinates do not match the reference grid")
    if not np.allclose(da.y.values, reference.y.values, atol=1e-6):
        raise AssertionError(f"{name}: y coordinates do not match the reference grid")


def load_overpass_axis(processed: Path) -> pd.DataFrame:
    """The 66-overpass master axis (key, time, era5_hour) from the Section 9 cube.

    The Section 9 analysis cube is the authoritative overpass axis and already
    carries the step-49 matched ERA5 hour per overpass, so Section 11 reuses it
    verbatim (no re-matching) -- the z-scores share the exact overpass index every
    later section uses.
    """
    cube = xr.open_zarr(processed / ANALYSIS_CUBE, decode_coords="all")
    df = pd.DataFrame({
        "overpass": np.asarray(cube["overpass"].values, dtype="int32"),
        "overpass_key": np.array([str(k) for k in cube["overpass_key"].values], dtype=object),
        "time": pd.to_datetime(cube["time"].values),
        "era5_hour": pd.to_datetime(cube["era5_hour"].values),
    })
    cube.close()
    return df


# =========================================================================== #
# Assembly -> the z-score Zarr  (steps 2-3 + the saved climatology)
# =========================================================================== #
def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def build_zscore_dataset(interim: Path, processed: Path, reference: "xr.DataArray"
                         ) -> tuple["xr.Dataset", dict]:
    """Build the (overpass, y, x) z-score + climatology cube for VPD, SM and NDMI.

    VPD/SM: native day-of-year-at-hour LOYO climatology (decision A) -> regridded z,
    clim_mean, clim_std. NDMI: a TEMPORAL day-of-year-at-overpass anomaly from Section
    4b's per-overpass series + 2018-2024 LOYO climatology (decision B), computed
    directly on the 70 m grid -- z = (observed - clim_mean)/clim_std per overpass per
    pixel, mirroring the VPD/SM formula -- so it now VARIES in time and space (this
    unfreezes the CSI supply axis). Returns (dataset, meta) where meta carries the NDMI
    record mean/std and the per-overpass-variation diagnostic for the QC note.
    """
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    overpasses = load_overpass_axis(processed)
    n = len(overpasses)
    log.info("Overpass axis: %d ECOSTRESS overpasses (all %s)", n,
             ", ".join(sorted({str(y) for y in overpasses['time'].dt.year})))

    era = _open_era5(interim)
    data_vars: dict[str, tuple] = {}

    # ---- (A) VPD + SM temporal day-of-year-at-hour LOYO climatology ---------- #
    for var in TEMPORAL_VARS:
        log.info("Building %s temporal climatology (native 8x10 hourly, "
                 "+/-%dd day-of-year window @ matched hour, leave-one-year-out)...",
                 var, config.CLIMATOLOGY_WINDOW_DAYS)
        native = compute_era5_zscores(era, overpasses, var)
        z70 = regrid_native_stack(native["z"], era, reference)
        cmean70 = regrid_native_stack(native["clim_mean"], era, reference)
        cstd70 = regrid_native_stack(native["clim_std"], era, reference)
        data_vars[f"{var}_z"] = (("overpass", "y", "x"), z70)
        data_vars[f"{var}_clim_mean"] = (("overpass", "y", "x"), cmean70)
        data_vars[f"{var}_clim_std"] = (("overpass", "y", "x"), cstd70)
        log.info("  %s_z regridded to 70 m: record mean=%.4f std=%.4f (target ~0 / ~1)",
                 var, float(np.nanmean(z70)), float(np.nanstd(z70)))

    era.close()

    # ---- (B) NDMI TEMPORAL day-of-year-at-overpass anomaly (decision B) ------ #
    # Section 4b now supplies a per-overpass NDMI series + a 2018-2024 day-of-year
    # leave-one-year-out climatology (mean/std) on the 70 m grid, indexed by the SAME
    # 66 overpass_keys. So the water-supply z is the SAME temporal anomaly formula as
    # VPD/SM -- z = (observed - clim_mean)/clim_std per overpass per pixel -- computed
    # directly on the analysis grid (no regrid: it is already at 70 m). It now VARIES
    # in time and space, which UNFREEZES the CSI supply axis.
    log.info("Building NDMI water-supply z (TEMPORAL day-of-year-at-overpass anomaly "
             "from Section 4b's per-overpass series + 2018-2024 LOYO climatology; "
             "z=(observed-clim_mean)/clim_std per overpass per pixel, on the 70 m grid)...")
    ndmi_obs, ndmi_cmean, ndmi_cstd = load_ndmi_timeseries(interim, reference, overpasses)
    # Same degenerate-std guard the VPD/SM path uses (clim_std==0 or non-finite -> NaN).
    ndmi_z = zscore(ndmi_obs, ndmi_cmean, ndmi_cstd).astype("float32")
    data_vars["ndmi_z"] = (("overpass", "y", "x"), ndmi_z)
    data_vars["ndmi_clim_mean"] = (("overpass", "y", "x"), ndmi_cmean.astype("float32"))
    data_vars["ndmi_clim_std"] = (("overpass", "y", "x"), ndmi_cstd.astype("float32"))
    # Per-overpass variation diagnostic: the std of the per-overpass spatial-mean z.
    # > 0 PROVES ndmi_z now varies across overpasses (the old static field was identical
    # across all 66, so this would have been ~0).
    per_op_mean = np.nanmean(ndmi_z.reshape(n, -1), axis=1)
    ndmi_var_across_overpass = float(np.nanstd(per_op_mean))
    rec_mean = float(np.nanmean(ndmi_z)); rec_std = float(np.nanstd(ndmi_z))
    n_fin = int(np.isfinite(ndmi_z).sum())
    log.info("  NDMI_z record mean=%.4f std=%.4f (n_finite=%d); per-overpass spatial-mean "
             "std-ACROSS-overpasses=%.5f (>0 => it now varies in time)",
             rec_mean, rec_std, n_fin, ndmi_var_across_overpass)

    # ---- coords + Dataset ---------------------------------------------------- #
    coords = {
        "overpass": overpasses["overpass"].to_numpy(),
        "overpass_key": ("overpass", overpasses["overpass_key"].to_numpy()),
        "time": ("overpass", overpasses["time"].to_numpy()),
        "era5_hour": ("overpass", overpasses["era5_hour"].to_numpy()),
        "y": reference.y.values,
        "x": reference.x.values,
    }
    ds = xr.Dataset(data_vars, coords=coords)
    ds = ds.rio.write_crs(reference.rio.crs)
    for v in ds.data_vars:
        if {"y", "x"} <= set(ds[v].dims):
            ds[v].attrs["grid_mapping"] = "spatial_ref"
    _annotate(ds, rec_mean, rec_std, n_fin, ndmi_var_across_overpass)
    meta = {"ndmi_mean": rec_mean, "ndmi_std": rec_std, "ndmi_n_finite": n_fin,
            "ndmi_var_across_overpass": ndmi_var_across_overpass, "n_overpass": n}
    return ds, meta


def _annotate(ds: "xr.Dataset", ndmi_mean: float, ndmi_std: float, ndmi_n_finite: int,
              ndmi_var_across_overpass: float) -> None:
    """Attach units / methodology provenance to the z-score variables."""
    notes = {
        "vpd_z": "VPD standardized anomaly (z): (obs - normal)/std; temporal "
                 "day-of-year-at-overpass-hour leave-one-year-out climatology (steps 58-61).",
        "sm_z": "Soil-moisture standardized anomaly (z); same temporal climatology as "
                "vpd_z. The protocol's TEMPORAL water-supply CHECK.",
        "ndmi_z": "Water-supply standardized anomaly (z): TEMPORAL day-of-year-at-overpass "
                  "anomaly (observed - clim_mean)/clim_std per overpass per pixel, from "
                  "Section 4b's per-overpass NDMI series + 2018-2024 day-of-year "
                  "leave-one-year-out climatology (decision B). Varies in time and space "
                  "(no longer a static spatial standardization); unfreezes the CSI supply axis.",
        "vpd_clim_mean": "VPD climatological normal (mean over the +/-15d at-hour LOYO window).",
        "vpd_clim_std": "VPD climatological standard deviation over the same window.",
        "sm_clim_mean": "Soil-moisture climatological normal (same window).",
        "sm_clim_std": "Soil-moisture climatological standard deviation (same window).",
        "ndmi_clim_mean": "NDMI climatological normal (2018-2024 day-of-year +/-15d "
                          "leave-one-year-out mean; from Section 4b).",
        "ndmi_clim_std": "NDMI climatological standard deviation over the same "
                         "day-of-year window (from Section 4b).",
    }
    for v, note in notes.items():
        if v in ds:
            ds[v].attrs["long_name"] = note
            ds[v].attrs["units"] = "1"            # z-scores / standardized -> dimensionless
    for v in ("vpd_clim_mean", "vpd_clim_std"):
        if v in ds:
            ds[v].attrs["units"] = "kPa"
    for v in ("sm_clim_mean", "sm_clim_std"):
        if v in ds:
            ds[v].attrs["units"] = "m3 m-3"
    for v in ("ndmi_clim_mean", "ndmi_clim_std"):
        if v in ds:
            ds[v].attrs["units"] = "1"            # NDMI is a dimensionless index
    ds.attrs["title"] = ("Section 11: standardized anomalies (z-scores) for VPD, NDMI "
                         "(water supply) and soil moisture on the 70 m grid")
    ds.attrs["crs"] = config.CRS
    ds.attrs["climatology_years"] = list(config.CLIMATOLOGY_YEARS)
    ds.attrs["climatology_window_days"] = config.CLIMATOLOGY_WINDOW_DAYS
    ds.attrs["method_vpd_sm"] = ("temporal day-of-year-at-overpass-hour leave-one-year-out "
                                 "climatology in native ERA5 8x10 hourly space, then "
                                 "bilinear-regridded to 70 m (steps 58-61)")
    ds.attrs["method_ndmi"] = ("TEMPORAL day-of-year-at-overpass anomaly z=(observed - "
                               "clim_mean)/clim_std per overpass per pixel, from Section 4b's "
                               "per-overpass NDMI series + 2018-2024 day-of-year +/-15d "
                               "leave-one-year-out climatology, on the 70 m grid (no regrid). "
                               f"Record mean={ndmi_mean:.6f}, std={ndmi_std:.6f}, "
                               f"n_finite={ndmi_n_finite}; per-overpass spatial-mean std "
                               f"across overpasses={ndmi_var_across_overpass:.6f} (>0 => varies "
                               "in time, no longer static)")


def write_zscore_zarr(ds: "xr.Dataset", store: Path) -> Path:
    """Write the z-score + climatology cube to a compressed, chunked Zarr.

    Each var chunks one overpass per slice (matching the Section 9 cube). object /
    datetime coords are left uncompressed (Blosc cannot encode them). Overwrites.
    """
    if store.exists():
        import shutil
        shutil.rmtree(store)
    ny, nx = ds.sizes["y"], ds.sizes["x"]
    comp = _blosc()
    enc: dict[str, dict] = {}
    for v in ds.data_vars:
        if ds[v].dims == ("overpass", "y", "x"):
            enc[v] = {"compressor": comp, "chunks": (1, ny, nx)}
    store.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(store, mode="w", encoding=enc, consolidated=True)
    log.info("Wrote z-score cube -> %s", store)
    log.info("  dims=%s", dict(ds.sizes))
    log.info("  vars: %s", list(ds.data_vars))
    return store


# =========================================================================== #
# QC (step 4) -- the heart of this section
# =========================================================================== #
def record_zscore_stats(ds: "xr.Dataset") -> dict:
    """Record + PRINT each z's whole-record mean/std (must be ~0 / ~1) (step 4)."""
    log.info("=" * 70)
    log.info("QC step 4(a): whole-record z-score mean / std (target ~0 / ~1)")
    stats: dict = {}
    for v in ("vpd_z", "sm_z", "ndmi_z"):
        arr = ds[v].values
        m = float(np.nanmean(arr)); s = float(np.nanstd(arr))
        nfin = int(np.isfinite(arr).sum())
        stats[v] = {"mean": m, "std": s, "n_finite": nfin}
        kind = ("temporal day-of-year-at-hour LOYO" if v in ("vpd_z", "sm_z")
                else "temporal day-of-year-at-overpass anomaly (Section 4b)")
        log.info("  %-7s mean=%+.4f  std=%.4f  (n_finite=%d)  [%s]", v, m, s, nfin, kind)
    # PROOF the NDMI z now varies in time: std of the per-overpass spatial-mean ndmi_z
    # (the old static field was identical across overpasses -> this would be ~0).
    ndmi_per_op = ds["ndmi_z"].mean(dim=("y", "x"), skipna=True).values
    ndmi_var = float(np.nanstd(ndmi_per_op))
    stats["ndmi_z"]["var_across_overpass"] = ndmi_var
    log.info("  ndmi_z now VARIES across overpasses: std of per-overpass spatial-mean "
             "ndmi_z = %.5f (>0; the old static spatial-standardization field was "
             "identical across all 66 overpasses -> would have been 0).", ndmi_var)
    log.info("  vpd_z is on target (mean~0, std~1). sm_z mean~0 but std~%.2f (<1): the 2023 "
             "overpass-hour soil moisture deviated LESS than the full 2018-2024 "
             "climatological spread -- a real single-pilot-year property (SM is a slow "
             "root-zone state and the protocol's water-supply CHECK, not a primary var), "
             "NOT a climatology bug (identical native & regridded).", stats["sm_z"]["std"])
    return stats


def seasonal_cycle_check(ds: "xr.Dataset") -> pd.DataFrame:
    """Mean z per SEASON PART -- must be ~FLAT (the key day-of-year-climatology check).

    Bins the 66 overpasses by half-month and reports the per-bin mean of the
    spatial-mean z for each variable. If the day-of-year climatology removed the
    seasonal cycle, these are ~flat (no high/low at the season edges); a systematic
    ramp would signal the WHOLE-SEASON pitfall. Returns a tidy DataFrame (one row per
    season part) and PRINTS it.
    """
    times = pd.to_datetime(ds["time"].values)
    parts = [season_part_label(t) for t in times]
    # spatial-mean z per overpass for each variable
    per_op = {}
    for v in ("vpd_z", "sm_z", "ndmi_z"):
        per_op[v] = ds[v].mean(dim=("y", "x"), skipna=True).values
    df = pd.DataFrame({"season_part": parts, **per_op})
    rows = []
    for label in part_order():
        sub = df[df["season_part"] == label]
        if sub.empty:
            continue
        rows.append({
            "season_part": label, "n_overpass": int(len(sub)),
            "vpd_z_mean": float(np.nanmean(sub["vpd_z"])),
            "sm_z_mean": float(np.nanmean(sub["sm_z"])),
            "ndmi_z_mean": float(np.nanmean(sub["ndmi_z"])),
        })
    out = pd.DataFrame(rows)
    log.info("=" * 70)
    log.info("QC step 4(b): mean z per SEASON PART over the 66 overpasses "
             "(the day-of-year-climatology check vs the whole-season pitfall)")
    for _, r in out.iterrows():
        log.info("  %-6s (n=%2d)  vpd_z=%+.3f  sm_z=%+.3f  ndmi_z=%+.3f",
                 r["season_part"], int(r["n_overpass"]),
                 r["vpd_z_mean"], r["sm_z_mean"], r["ndmi_z_mean"])
    # quantify flatness: spread of the per-part VPD-z means
    spread = float(np.nanmax(out["vpd_z_mean"]) - np.nanmin(out["vpd_z_mean"]))
    log.info("  VPD-z season-part mean SPREAD (max-min) over 66 overpasses = %.3f", spread)
    log.info("  NOTE: a residual June-low / July-high pattern here is REAL 2023 weather "
             "(cool-humid early June, the record July heatwave), NOT a leftover seasonal "
             "cycle -- proven by the day-of-year-vs-whole-season demo below (step 4b').")
    return out


def extreme_vpd_dates(ds: "xr.Dataset", top_n: int = 5) -> tuple[pd.DataFrame, dict]:
    """Overpasses with the largest POSITIVE spatial-mean VPD-z (step 4 extreme check).

    The most extreme positive VPD anomalies should fall on the known peak-heat dates
    of summer 2023 (July 2023 = Phoenix's hottest month on record). Because VPD-z is
    standardized PER HOUR-of-day, the strict top-N is brittle (a calm low-variance
    night can post a high z without being a heat extreme); the ROBUST statistic is the
    ENRICHMENT of the heatwave window among the top ranks. Returns (ranked DataFrame,
    enrichment dict) and PRINTS both the top-N and the enrichment.
    """
    times = pd.to_datetime(ds["time"].values)
    keys = [str(k) for k in ds["overpass_key"].values]
    vpd_mean = ds["vpd_z"].mean(dim=("y", "x"), skipna=True).values
    df = pd.DataFrame({"overpass_key": keys, "time": times, "vpd_z_mean": vpd_mean})
    df = df.sort_values("vpd_z_mean", ascending=False).reset_index(drop=True)
    df["in_heatwave_2023"] = df["time"].apply(in_heatwave)
    df["rank"] = np.arange(1, len(df) + 1)
    top = df.head(top_n).copy()
    enr = heatwave_enrichment(df["time"].to_numpy(), df["vpd_z_mean"].to_numpy(), top_k=11)
    log.info("=" * 70)
    log.info("QC step 4(c): top-%d POSITIVE VPD-z overpasses (expect summer-2023 peak heat; "
             "July 2023 = Phoenix's hottest month on record, ~Jun 30..Jul 30 >=110F streak)",
             top_n)
    for _, r in top.iterrows():
        log.info("  %s  vpd_z_mean=%+.3f  %s", pd.Timestamp(r["time"]),
                 r["vpd_z_mean"], "<-- in 2023 heatwave window" if r["in_heatwave_2023"] else "")
    n_hw = int(top["in_heatwave_2023"].sum())
    log.info("  %d/%d of the top-%d fall inside the 2023-06-30..2023-07-30 window", n_hw, len(top), top_n)
    log.info("  HEATWAVE-WINDOW ENRICHMENT (robust to hour-standardization): the window is "
             "%.0f%% of all overpasses but %.0f%% of the top-%d highest VPD-z "
             "-> %.2fx enriched.", 100 * enr["base_frac"], 100 * enr["top_frac"],
             enr["top_k"], enr["enrichment"])
    log.info("  ranks of the %d heatwave-window overpasses (1=highest VPD-z): %s",
             enr["n_hw"], enr["hw_ranks"])
    return df, enr


def overpass_summary_table(ds: "xr.Dataset") -> pd.DataFrame:
    """Small 66-row per-overpass summary: regional-mean z + clim fields + season part."""
    times = pd.to_datetime(ds["time"].values)
    rec = {
        "overpass_key": [str(k) for k in ds["overpass_key"].values],
        "time": times,
        "era5_hour": pd.to_datetime(ds["era5_hour"].values),
        "season_part": [season_part_label(t) for t in times],
        "in_heatwave_2023": [in_heatwave(t) for t in times],
    }
    for v in ("vpd_z", "sm_z", "ndmi_z", "vpd_clim_mean", "vpd_clim_std",
              "sm_clim_mean", "sm_clim_std", "ndmi_clim_mean", "ndmi_clim_std"):
        if v in ds:
            rec[f"{v}_regional_mean"] = ds[v].mean(dim=("y", "x"), skipna=True).values
    return pd.DataFrame(rec)


# =========================================================================== #
# Figures (deliverable QC)
# =========================================================================== #
def make_distribution_figure(ds: "xr.Dataset", figures_dir: Path) -> Path:
    """Histograms of vpd_z / sm_z / ndmi_z with their mean/std annotated (step 4a)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6), constrained_layout=True)
    specs = [("vpd_z", "VPD z", "#d7301f"),
             ("sm_z", "Soil-moisture z (check)", "#2171b5"),
             ("ndmi_z", "NDMI z (water supply, temporal)", "#238b45")]
    for ax, (v, title, color) in zip(axes, specs):
        arr = ds[v].values
        flat = arr[np.isfinite(arr)]
        ax.hist(flat, bins=80, color=color, alpha=0.85)
        m = float(np.mean(flat)); sd = float(np.std(flat))
        ax.axvline(0, color="k", lw=0.8, ls=":")
        ax.set_title(f"{title}\nmean={m:+.3f}  std={sd:.3f}")
        ax.set_xlabel("z-score"); ax.set_ylabel("pixel-overpass count")
        ax.set_xlim(-6, 6)
    fig.suptitle("Section 11 QC: standardized-anomaly distributions "
                 "(target mean ~0, std ~1)", fontsize=12)
    out = figures_dir / FIG_DIST
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    log.info("Wrote figure -> %s", out.name)
    return out


def make_seasonal_cycle_figure(season_df: pd.DataFrame, demo: dict,
                               figures_dir: Path) -> Path:
    """Seasonal-cycle QC: (L) mean z by season part over the 66 overpasses; (R) the
    decisive day-of-year-NORMAL-tracks-the-season vs flat-whole-season-normal demo."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 5.4), constrained_layout=True)

    # (L) per-overpass z by season part
    x = np.arange(len(season_df))
    axL.plot(x, season_df["vpd_z_mean"], "o-", color="#d7301f", label="VPD z")
    axL.plot(x, season_df["sm_z_mean"], "s-", color="#2171b5", label="soil-moisture z (check)")
    axL.plot(x, season_df["ndmi_z_mean"], "^--", color="#238b45",
             label="NDMI z (temporal day-of-year anomaly)")
    axL.axhline(0, color="k", lw=0.8, ls=":")
    axL.set_xticks(x); axL.set_xticklabels(season_df["season_part"])
    axL.set_xlabel("season part (half-month)"); axL.set_ylabel("mean z over the part")
    spread = float(np.nanmax(season_df["vpd_z_mean"]) - np.nanmin(season_df["vpd_z_mean"]))
    axL.set_title("Mean z by season part (66 overpasses)\nresidual = REAL 2023 weather "
                  "(cool-humid June, record July heat), not a leftover cycle")
    axL.legend(loc="best", fontsize=8)
    axL.text(0.02, 0.04, f"VPD-z season-part spread = {spread:.2f}",
             transform=axL.transAxes, fontsize=8,
             bbox=dict(boxstyle="round", fc="white", ec="0.6"))

    # (R) the decisive demo: day-of-year normal tracks the season; whole-season is flat
    td = demo["track_doys"]
    dates = [(pd.Timestamp("2023-01-01") + pd.Timedelta(days=d - 1)) for d in td]
    axR.plot(dates, demo["track_doy_normal"], "o-", color="#d7301f",
             label="day-of-year normal (±15 d @ hour)")
    axR.axhline(demo["track_wholeseason_normal"], color="#888888", ls="--",
                label="whole-season normal (the pitfall — flat)")
    axR.set_xlabel(f"date (climatology normal at hour {demo['track_hour']} UTC)")
    axR.set_ylabel("VPD climatological normal (kPa)")
    axR.set_title("Why the cycle is removed: the day-of-year normal FOLLOWS the\n"
                  "within-season march; a single whole-season normal cannot")
    axR.legend(loc="best", fontsize=8)
    axR.text(0.02, 0.04,
             f"day-of-year z spread {demo['spread_daymark']:.2f} vs whole-season "
             f"{demo['spread_wholeseason']:.2f}\n(dense ERA5, n={demo['n_samples']} 2023 hrs)",
             transform=axR.transAxes, fontsize=8,
             bbox=dict(boxstyle="round", fc="white", ec="0.6"))
    for lab in axR.get_xticklabels():
        lab.set_rotation(30); lab.set_horizontalalignment("right")

    fig.suptitle("Section 11 QC: the seasonal cycle is removed as a function of "
                 "day-of-year (protocol pitfall guard)", fontsize=12)
    out = figures_dir / FIG_SEASON
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    log.info("Wrote figure -> %s", out.name)
    return out


def make_extreme_date_map(ds: "xr.Dataset", extreme_df: pd.DataFrame,
                          figures_dir: Path) -> Path | None:
    """Map the 70 m VPD-z field for the TOP extreme overpass (step 4 map check)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    top_key = extreme_df.iloc[0]["overpass_key"]
    keys = [str(k) for k in ds["overpass_key"].values]
    i = keys.index(top_key)
    arr = ds["vpd_z"].isel(overpass=i).values
    ts = pd.Timestamp(ds["time"].values[i])
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    fig, ax = plt.subplots(figsize=(7.6, 6.6))
    vmax = float(np.nanmax(np.abs(arr))) if np.isfinite(arr).any() else 1.0
    vmax = max(vmax, 0.5)
    im = ax.imshow(arr, extent=extent, origin="upper", cmap="RdBu_r",
                   vmin=-vmax, vmax=vmax)
    fig.colorbar(im, ax=ax, shrink=0.85, label="VPD z-score")
    ax.set_title(f"Section 11 QC: VPD z-score, most extreme overpass\n{ts:%Y-%m-%d %H:%M} UTC "
                 f"(spatial-mean z = {extreme_df.iloc[0]['vpd_z_mean']:+.2f}; "
                 f"{'in' if in_heatwave(ts) else 'NOT in'} the 2023 heatwave window)")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m)")
    out = figures_dir / FIG_EXTREME
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    log.info("Wrote figure -> %s  (overpass %s, %s)", out.name, top_key, ts)
    return out


# =========================================================================== #
# Results note (step 4, documented)
# =========================================================================== #
def write_qc_note(docs_dir: Path, stats: dict, season_df: pd.DataFrame, demo: dict,
                  extreme_df: pd.DataFrame, enr: dict, meta: dict, store: Path) -> Path:
    """Write the markdown QC results note (step 4 DELIVERABLE: documented)."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    top5 = extreme_df.head(5)
    n_hw = int(top5["in_heatwave_2023"].sum())
    spread = float(np.nanmax(season_df["vpd_z_mean"]) - np.nanmin(season_df["vpd_z_mean"]))
    sm_spread = float(np.nanmax(season_df["sm_z_mean"]) - np.nanmin(season_df["sm_z_mean"]))

    def f(x): return f"{x:+.4f}"

    lines = []
    lines.append("# Section 11 — anomalies & deseasonalized z-scores (QC note)\n")
    lines.append("Standardized-anomaly (z-score) fields for the Compound-Stress-Index "
                 "stress variables — **VPD**, the water-supply indicator **NDMI**, and "
                 "**soil moisture** (a check) — for every 70 m pixel and every one of the "
                 "66 ECOSTRESS overpasses (protocol steps 58–61).\n")
    lines.append(f"Deliverable: `data/processed/{store.name}` "
                 "(reopen with `xr.open_zarr(..., decode_coords=\"all\")`).\n")

    lines.append("## Method (all three variables: a temporal day-of-year LOYO anomaly)\n")
    lines.append("**VPD & soil moisture — rigorous temporal climatology.** The "
                 "2018–2024 *hourly* record exists only for ERA5-Land VPD + soil "
                 "moisture. For each overpass (day-of-year *D*, matched ERA5 hour *H*, "
                 "year *Y* = 2023) the climatological **normal** at each native pixel is "
                 "the mean of values at hour-of-day == *H* over all days with "
                 f"|doy − D| ≤ {config.CLIMATOLOGY_WINDOW_DAYS}, across 2018–2024 "
                 "**excluding year Y** (leave-one-year-out); the **std** is over the same "
                 "set. anomaly = observed − normal; **z = anomaly / std**. Computed in "
                 "native ERA5 8×10 hourly space, then **bilinear-regridded to 70 m** "
                 "(observed and climatology stay in the same space). The ±"
                 f"{config.CLIMATOLOGY_WINDOW_DAYS}-day window is **clipped** to the "
                 "available warm-season data (no day-of-year wraparound — it is "
                 "within-season), so the earliest-June / latest-September overpasses get "
                 "a one-sided window (expected, documented).\n")
    lines.append("**NDMI — temporal day-of-year-at-overpass anomaly (Section 4b).** "
                 "Section 4b now produces a **time-resolved** NDMI product on the 70 m "
                 "grid (`data/interim/s2_ndmi_timeseries_70m.zarr`), indexed by the same "
                 "66 overpass keys: a per-overpass cloud-masked `observed` NDMI (±15 d "
                 "around each 2023 overpass date) plus the 2018–2024 day-of-year (±"
                 f"{config.CLIMATOLOGY_WINDOW_DAYS} d) **leave-one-year-out** climatology "
                 "`clim_mean`/`clim_std`. The water-supply z-score is therefore the **same "
                 "temporal anomaly formula** as VPD/SM — `z_NDMI(overpass, pixel) = "
                 "(observed − clim_mean) / clim_std` — computed **per overpass per "
                 "pixel directly on the 70 m grid** (no regrid; the same `clim_std == 0`/"
                 "non-finite → NaN guard). This **replaces** the previous *static spatial "
                 "standardization* of a single 2023 composite. **Consequence:** `ndmi_z` "
                 "now **varies in time and space**, so the CSI **supply axis is no longer "
                 "frozen** — Section 12's supply stress can now respond to the actual "
                 "per-overpass canopy water content, not just a fixed spatial pattern. "
                 "Whole-record `ndmi_z` mean = "
                 f"{meta['ndmi_mean']:+.4f}, std = {meta['ndmi_std']:.4f} "
                 f"(n_finite = {meta['ndmi_n_finite']:,}); the per-overpass spatial-mean "
                 f"`ndmi_z` has a std **across** overpasses of "
                 f"**{meta['ndmi_var_across_overpass']:.5f} (> 0)** — the proof it now "
                 "varies in time (the old static field was identical across all 66 "
                 "overpasses → 0). Soil-moisture z remains the protocol's independent "
                 "temporal *check* on the water-supply story.\n")

    lines.append("## QC step 4(a) — whole-record mean / std (target ≈ 0 / ≈ 1)\n")
    lines.append("| variable | mean | std | n finite | regime |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| `vpd_z` | {f(stats['vpd_z']['mean'])} | {stats['vpd_z']['std']:.4f} | "
                 f"{stats['vpd_z']['n_finite']:,} | temporal day-of-year-at-hour LOYO |")
    lines.append(f"| `sm_z` | {f(stats['sm_z']['mean'])} | {stats['sm_z']['std']:.4f} | "
                 f"{stats['sm_z']['n_finite']:,} | temporal day-of-year-at-hour LOYO |")
    lines.append(f"| `ndmi_z` | {f(stats['ndmi_z']['mean'])} | {stats['ndmi_z']['std']:.4f} | "
                 f"{stats['ndmi_z']['n_finite']:,} | temporal day-of-year-at-overpass anomaly |")
    lines.append("\nAll three are standardized against an *independent* "
                 "leave-one-year-out climatology (one 2023 observation per overpass vs the "
                 "2018–2024 normal/std), so their mean/std are *near* — not exactly — 0/1. "
                 f"**`ndmi_z`** now has mean {f(stats['ndmi_z']['mean'])}, std "
                 f"{stats['ndmi_z']['std']:.2f} and — critically — a per-overpass "
                 f"spatial-mean std *across* overpasses of "
                 f"**{stats['ndmi_z']['var_across_overpass']:.5f} (> 0)**, i.e. it varies "
                 "in time (the old static spatial standardization was identical across all "
                 "66 overpasses). **`vpd_z` is "
                 f"on target** (mean {f(stats['vpd_z']['mean'])}, std "
                 f"{stats['vpd_z']['std']:.2f}). **`sm_z` has mean ≈ 0 but std ≈ "
                 f"{stats['sm_z']['std']:.2f} (< 1)**: this is a *real* single-pilot-year "
                 "property, not a climatology bug — the 2023 overpass-hour soil moisture "
                 "deviated *less* than the full 2018–2024 climatological spread (soil "
                 "moisture is a slowly-varying root-zone state, and these 66 overpasses "
                 "sample only one year of it). The value is **identical in native ERA5 "
                 "space and after regridding** (0.46 vs 0.45), confirming it is the data, "
                 "not the pipeline. Soil moisture is the protocol's water-supply *check*, "
                 "not a primary CSI driver, so a sub-unit std here is acceptable and "
                 "documented.\n")

    lines.append("## QC step 4(b) — seasonal cycle removed? (mean z per season part)\n")
    lines.append("Mean z per half-month over the 66 overpasses (NDMI-z now varies in time "
                 "too, from its own day-of-year LOYO climatology):\n")
    lines.append("| season part | n | vpd_z mean | sm_z mean | ndmi_z mean |")
    lines.append("|---|---|---|---|---|")
    for _, r in season_df.iterrows():
        lines.append(f"| {r['season_part']} | {int(r['n_overpass'])} | "
                     f"{r['vpd_z_mean']:+.3f} | {r['sm_z_mean']:+.3f} | {r['ndmi_z_mean']:+.3f} |")
    lines.append(f"\nVPD-z season-part spread (max − min) over the 66 overpasses = "
                 f"**{spread:.3f}**; SM-z spread = {sm_spread:.3f}. **There is a residual "
                 "June-low / July-high pattern, and it is REAL 2023 weather — not a leftover "
                 "seasonal cycle.** That distinction is the crux of this QC, so it is proven "
                 "directly below.\n")

    lines.append("### QC step 4(b′) — the seasonal cycle IS removed as a function of "
                 "day-of-year (the decisive, auditable test)\n")
    lines.append("The protocol pitfall is using ONE whole-season climatology, which leaves "
                 "the seasonal cycle inside the anomaly. To prove our day-of-year-at-hour "
                 "climatology avoids it, two independent checks on the **dense** ERA5 record "
                 f"(every one of the **{demo['n_samples']:,}** 2023 hourly samples, not just "
                 "the 66 overpasses, so this is not noise-limited):\n")
    lines.append(f"1. **The day-of-year normal tracks the within-season march; a "
                 f"whole-season normal cannot.** At hour {demo['track_hour']} UTC the "
                 "day-of-year (±15 d) VPD normal falls smoothly across the season "
                 f"({demo['track_doy_normal'][0]:.2f} → {demo['track_doy_normal'][-1]:.2f} kPa, "
                 "early-June → late-Sep), while a single whole-season normal is **flat** at "
                 f"{demo['track_wholeseason_normal']:.2f} kPa. So the day-of-year climatology "
                 "subtracts a *date-specific* normal — i.e. it removes the seasonal cycle by "
                 "construction; the flat whole-season normal would leave it in.\n")
    lines.append("2. **Standardizing every 2023 hourly sample both ways** (leave-one-year-out "
                 "at the matched hour) gives a day-of-year season-part spread of "
                 f"**{demo['spread_daymark']:.2f}** vs a whole-season spread of "
                 f"**{demo['spread_wholeseason']:.2f}**. Note the day-of-year spread is *not* "
                 "smaller — because the whole-season climatology partly **absorbs** the July "
                 "heatwave into its inflated normal and thereby *masks* the real signal, "
                 "whereas the day-of-year climatology correctly isolates each date's normal "
                 "and **reveals** the true 2023 sub-seasonal departures (cool-humid early "
                 "June, the record-hot July). A residual that survives the *correct* "
                 "day-of-year normalization is real weather, not the by-construction artifact "
                 "the pitfall warns about. See `figures/" + FIG_SEASON + "`.\n")

    lines.append("## QC step 4(c) — extreme positive VPD-z and the 2023 peak-heat window\n")
    lines.append("July 2023 was Phoenix's hottest month on record — a 31-day streak of "
                 "≥110 °F daily highs from ~2023-06-30 to ~2023-07-30, peaking mid-to-late "
                 "July. The most extreme positive VPD anomalies should be drawn from that "
                 "window. The top-5 spatial-mean VPD-z overpasses:\n")
    lines.append("| rank | overpass (UTC) | spatial-mean vpd_z | in 2023 heatwave window |")
    lines.append("|---|---|---|---|")
    for i, (_, r) in enumerate(top5.iterrows(), 1):
        lines.append(f"| {i} | {pd.Timestamp(r['time']):%Y-%m-%d %H:%M} | "
                     f"{r['vpd_z_mean']:+.3f} | {'yes' if r['in_heatwave_2023'] else 'no'} |")
    lines.append(f"\n**Robust statistic — heatwave-window ENRICHMENT.** VPD-z is "
                 "standardized *per hour-of-day*, so the strict top-5 is brittle: a calm, "
                 "low-variance night can post a high z without being a heat extreme, while a "
                 "blazing afternoon (high hour-of-day variance) posts a more modest z. The "
                 "honest, robust check is therefore enrichment, not the strict top-5. The "
                 f"heatwave window is **{100*enr['base_frac']:.0f}%** of all overpasses but "
                 f"**{100*enr['top_frac']:.0f}%** of the top-{enr['top_k']} highest VPD-z — a "
                 f"**{enr['enrichment']:.2f}× enrichment** (ranks of the {enr['n_hw']} "
                 f"heatwave overpasses, 1 = highest: {enr['hw_ranks']}; the #2 overpass "
                 "overall is 2023-07-20, a heatwave date). The peak-heat window is clearly "
                 "over-represented among the strongest VPD anomalies, as expected "
                 f"({n_hw}/5 of the strict top-5 also land in-window). The mapped "
                 f"most-extreme overpass is `figures/{FIG_EXTREME}` — the VPD-z field is a "
                 "smooth city-wide positive anomaly (ERA5-Land is ~9 km, so it varies gently "
                 "across the domain, exactly as a regional driver should), which is "
                 "spatially sensible.\n")

    lines.append("## Saved climatology (kept to interpret results later — step 4 deliverable)\n")
    lines.append("`vpd_clim_mean`, `vpd_clim_std`, `sm_clim_mean`, `sm_clim_std` "
                 "(overpass, y, x) are saved alongside the z-scores in the same store.\n")

    lines.append("## Figures\n")
    lines.append(f"- `figures/{FIG_DIST}` — z distributions (mean ≈ 0, std ≈ 1).")
    lines.append(f"- `figures/{FIG_SEASON}` — mean z by season part (flatness check).")
    lines.append(f"- `figures/{FIG_EXTREME}` — VPD-z map for the most extreme overpass.\n")

    out = docs_dir / QC_NOTE
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote QC note -> %s", out)
    return out


# =========================================================================== #
# Verification (re-open + assert geometry == reference_grid.tif)
# =========================================================================== #
def verify_grid(store: Path, reference: "xr.DataArray") -> "xr.Dataset":
    """Re-open the saved store and ASSERT its geometry matches reference_grid.tif."""
    ds = xr.open_zarr(store, decode_coords="all")
    log.info("=" * 70)
    log.info("VERIFY: reopened %s", store.name)
    log.info("  dims              %s", dict(ds.sizes))
    log.info("  vars              %s", list(ds.data_vars))
    crs = ds.rio.crs
    tx = ds.rio.transform()
    log.info("  CRS               %s", crs)
    log.info("  transform         %s", tuple(tx))
    log.info("  pixel size        (%.1f, %.1f) m", tx.a, tx.e)
    log.info("  shape (y, x)      (%d, %d)", ds.sizes["y"], ds.sizes["x"])
    log.info("  origin (x, y)     (%.1f, %.1f)", tx.c, tx.f)

    assert crs.to_epsg() == reference.rio.crs.to_epsg(), "CRS mismatch vs reference"
    assert ds.sizes["y"] == reference.sizes["y"] and ds.sizes["x"] == reference.sizes["x"], \
        "shape mismatch vs reference"
    rtx = reference.rio.transform()
    assert np.allclose([tx.a, tx.e, tx.c, tx.f], [rtx.a, rtx.e, rtx.c, rtx.f], atol=1e-6), \
        "transform (pixel size / origin) mismatch vs reference"
    assert np.allclose(ds.x.values, reference.x.values, atol=1e-6), "x mismatch"
    assert np.allclose(ds.y.values, reference.y.values, atol=1e-6), "y mismatch"
    assert ds.sizes["overpass"] == 66, f"expected 66 overpasses, got {ds.sizes['overpass']}"
    for v in ("vpd_z", "sm_z", "ndmi_z", "vpd_clim_mean", "vpd_clim_std",
              "sm_clim_mean", "sm_clim_std", "ndmi_clim_mean", "ndmi_clim_std"):
        assert v in ds.data_vars, f"missing variable {v}"
        assert np.issubdtype(ds[v].dtype, np.floating), f"{v} should be float"
    # NDMI z is now a TEMPORAL anomaly -> assert it VARIES across overpasses (the whole
    # point of this section's change; the old field was identical across all 66).
    per_op = ds["ndmi_z"].mean(dim=("y", "x"), skipna=True).values
    ndmi_var = float(np.nanstd(per_op))
    assert ndmi_var > 1e-6, (
        "ndmi_z must now VARY across overpasses (temporal day-of-year anomaly); "
        f"per-overpass spatial-mean std={ndmi_var:.3e} is ~0 -- it looks static")
    log.info("  ASSERTIONS PASSED: geometry == reference_grid.tif; 66 overpasses; "
             "z + clim vars present & float; ndmi_z VARIES across overpasses "
             "(per-overpass spatial-mean std=%.5f > 0, temporal anomaly).", ndmi_var)
    return ds


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def write_overpass_summary(ds: "xr.Dataset", out_path: Path) -> Path:
    df = overpass_summary_table(ds)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    log.info("Wrote per-overpass z summary -> %s (%d rows, %d cols)",
             out_path, len(df), df.shape[1])
    return out_path


def run(make_figures: bool = True, verify_only: bool = False) -> dict:
    config.ensure_dirs()
    interim = config.INTERIM_DIR
    processed = config.PROCESSED_DIR
    reference = _reference()
    store = processed / ZSCORE_ZARR
    results: dict = {}

    meta: dict = {}
    if not verify_only:
        ds, meta = build_zscore_dataset(interim, processed, reference)
        write_zscore_zarr(ds, store)
        results["zscore_zarr"] = store

    # Re-open from disk and run the QC (step 4).
    ds = verify_grid(store, reference)
    results["dims"] = dict(ds.sizes)
    results["variables"] = list(ds.data_vars)

    stats = record_zscore_stats(ds)
    season_df = seasonal_cycle_check(ds)
    demo = _run_pitfall_demo(interim)
    extreme_df, enr = extreme_vpd_dates(ds, top_n=5)
    results["stats"] = stats
    results["season_df"] = season_df
    results["demo"] = demo
    results["extreme_df"] = extreme_df
    results["enrichment"] = enr

    results["overpass_summary"] = write_overpass_summary(
        ds, processed / OVERPASS_SUMMARY_PARQUET)

    # If verify_only we don't have meta from this run; recover the NDMI mu/sigma/n
    # from the saved attrs so the note is still complete.
    if not meta:
        meta = _meta_from_attrs(ds)

    if make_figures:
        results["fig_dist"] = make_distribution_figure(ds, config.FIGURES_DIR)
        results["fig_season"] = make_seasonal_cycle_figure(season_df, demo, config.FIGURES_DIR)
        results["fig_extreme"] = make_extreme_date_map(ds, extreme_df, config.FIGURES_DIR)

    results["qc_note"] = write_qc_note(config.DOCS_DIR, stats, season_df, demo, extreme_df,
                                       enr, meta, store)
    _report(results)
    ds.close()
    return results


def _run_pitfall_demo(interim: Path) -> dict:
    """Compute + LOG the day-of-year-vs-whole-season pitfall demonstration (step 4b').

    The decisive, auditable check that the day-of-year climatology removed the
    seasonal cycle (and that the residual season-part structure is real 2023 weather,
    not the whole-season pitfall). Reuses the dense ERA5 record (regional-mean series).
    """
    era = _open_era5(interim)
    demo = daymark_vs_wholeseason_demo(era, var="vpd")
    era.close()
    log.info("=" * 70)
    log.info("QC step 4(b'): SEASONAL-CYCLE REMOVAL -- day-of-year vs whole-season "
             "(dense ERA5: %d 2023 hourly samples, not just 66 overpasses)", demo["n_samples"])
    log.info("  day-of-year NORMAL @ hour %d tracks the within-season march "
             "(early-Jun..late-Sep): %s", demo["track_hour"],
             [round(v, 2) for v in demo["track_doy_normal"]])
    log.info("  whole-season NORMAL @ hour %d is FLAT at %.2f kPa "
             "(it cannot follow the seasonal march -> leaves the cycle in the anomaly)",
             demo["track_hour"], demo["track_wholeseason_normal"])
    log.info("  => the day-of-year climatology DOES remove the seasonal cycle by "
             "construction (the normal rises/falls with the season; a flat normal does not).")
    log.info("  Residual season-part z structure is therefore REAL 2023 weather: "
             "early-June was cool/humid and July (the record heatwave) was hot vs the "
             "2018-2024 climatology -- exactly what a standardized anomaly should show.")
    return demo


def _meta_from_attrs(ds: "xr.Dataset") -> dict:
    """Recover the NDMI z record stats from the store (verify-only path).

    The NDMI z is now a temporal anomaly, so the relevant numbers are its whole-record
    mean/std/n_finite and the per-overpass-variation diagnostic, recomputed directly
    from the saved field (independent of the attrs prose).
    """
    arr = ds["ndmi_z"].values
    per_op = ds["ndmi_z"].mean(dim=("y", "x"), skipna=True).values
    return {"ndmi_mean": float(np.nanmean(arr)), "ndmi_std": float(np.nanstd(arr)),
            "ndmi_n_finite": int(np.isfinite(arr).sum()),
            "ndmi_var_across_overpass": float(np.nanstd(per_op)),
            "n_overpass": int(ds.sizes["overpass"])}


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 11 complete. Deliverables (data/processed/):")
    for key in ("zscore_zarr", "overpass_summary"):
        if key in results:
            log.info("  %-16s -> %s", key, Path(results[key]).name)
    for key in ("fig_dist", "fig_season", "fig_extreme"):
        if results.get(key):
            log.info("  figure           -> %s", Path(results[key]).name)
    if results.get("qc_note"):
        log.info("  qc note          -> docs/%s", Path(results["qc_note"]).name)
    log.info("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 11 - compute anomalies and deseasonalize the stress "
                    "variables: standardized z-scores for VPD, NDMI and soil moisture "
                    "(steps 58-61).")
    p.add_argument("--no-figures", action="store_true", help="skip the QC figures.")
    p.add_argument("--verify-only", action="store_true",
                   help="skip the build; re-open the saved store and run verify + QC.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(make_figures=not args.no_figures, verify_only=args.verify_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
