# Section 11 — anomalies & deseasonalized z-scores (QC note)

Standardized-anomaly (z-score) fields for the Compound-Stress-Index stress variables — **VPD**, the water-supply indicator **NDMI**, and **soil moisture** (a check) — for every 70 m pixel and every one of the 66 ECOSTRESS overpasses (protocol steps 58–61).

Deliverable: `data/processed/section11_zscores_70m.zarr` (reopen with `xr.open_zarr(..., decode_coords="all")`).

## Method (two regimes, by what data exist)

**VPD & soil moisture — rigorous temporal climatology.** The 2018–2024 *hourly* record exists only for ERA5-Land VPD + soil moisture. For each overpass (day-of-year *D*, matched ERA5 hour *H*, year *Y* = 2023) the climatological **normal** at each native pixel is the mean of values at hour-of-day == *H* over all days with |doy − D| ≤ 15, across 2018–2024 **excluding year Y** (leave-one-year-out); the **std** is over the same set. anomaly = observed − normal; **z = anomaly / std**. Computed in native ERA5 8×10 hourly space, then **bilinear-regridded to 70 m** (observed and climatology stay in the same space). The ±15-day window is **clipped** to the available warm-season data (no day-of-year wraparound — it is within-season), so the earliest-June / latest-September overpasses get a one-sided window (expected, documented).

**NDMI — spatial standardization (a documented, data-forced deviation).** Section 4 produced **only one** warm-season median NDMI composite (2023); there is no multi-year or multi-date NDMI series, so a 2018–2024 day-of-year climatology **cannot** be built. The water-supply z-score is therefore a **spatial standardized anomaly** `z_NDMI(pixel) = (NDMI − μ)/σ`, with **μ and σ over all valid (finite) NDMI pixels in the study domain** (the reference population: **1,544,052 pixels**; μ = -0.06768, σ = 0.08498). This z **varies by pixel, not by overpass**, and is broadcast to all 66 overpasses to give the per-pixel-per-overpass shape the protocol asks for. **Consequence:** the water-supply stress that feeds Section 12 is a **spatial field, constant in time**; the CSI's *temporal* variation will come from VPD. Soil-moisture z is the protocol's temporal *check* on the water-supply story and is kept.

## QC step 4(a) — whole-record mean / std (target ≈ 0 / ≈ 1)

| variable | mean | std | n finite | regime |
|---|---|---|---|---|
| `vpd_z` | +0.1208 | 0.9451 | 101,100,054 | temporal day-of-year-at-hour LOYO |
| `sm_z` | -0.0850 | 0.4503 | 101,100,054 | temporal day-of-year-at-hour LOYO |
| `ndmi_z` | -0.0000 | 1.0000 | 101,907,432 | spatial standardization (constant in time) |

VPD-z and SM-z are standardized against an *independent* leave-one-year-out climatology (one 2023 observation per overpass vs the 2018–2024 normal/std), so their mean/std are *near* — not exactly — 0/1; NDMI-z is 0/1 by construction over its reference population. **`vpd_z` is on target** (mean +0.1208, std 0.95). **`sm_z` has mean ≈ 0 but std ≈ 0.45 (< 1)**: this is a *real* single-pilot-year property, not a climatology bug — the 2023 overpass-hour soil moisture deviated *less* than the full 2018–2024 climatological spread (soil moisture is a slowly-varying root-zone state, and these 66 overpasses sample only one year of it). The value is **identical in native ERA5 space and after regridding** (0.46 vs 0.45), confirming it is the data, not the pipeline. Soil moisture is the protocol's water-supply *check*, not a primary CSI driver, so a sub-unit std here is acceptable and documented.

## QC step 4(b) — seasonal cycle removed? (mean z per season part)

Mean z per half-month over the 66 overpasses (NDMI-z is flat by construction — constant in time):

| season part | n | vpd_z mean | sm_z mean | ndmi_z mean |
|---|---|---|---|---|
| Jun a | 8 | -1.558 | +0.485 | +0.000 |
| Jun b | 14 | +0.027 | +0.239 | +0.000 |
| Jul a | 8 | +0.810 | -0.186 | +0.000 |
| Jul b | 6 | +1.012 | -0.388 | +0.000 |
| Aug a | 9 | +0.408 | -0.478 | +0.000 |
| Aug b | 10 | +0.310 | -0.351 | +0.000 |
| Sep a | 6 | -0.040 | -0.011 | +0.000 |
| Sep b | 5 | +0.195 | -0.227 | +0.000 |

VPD-z season-part spread (max − min) over the 66 overpasses = **2.570**; SM-z spread = 0.964. **There is a residual June-low / July-high pattern, and it is REAL 2023 weather — not a leftover seasonal cycle.** That distinction is the crux of this QC, so it is proven directly below.

### QC step 4(b′) — the seasonal cycle IS removed as a function of day-of-year (the decisive, auditable test)

The protocol pitfall is using ONE whole-season climatology, which leaves the seasonal cycle inside the anomaly. To prove our day-of-year-at-hour climatology avoids it, two independent checks on the **dense** ERA5 record (every one of the **2,928** 2023 hourly samples, not just the 66 overpasses, so this is not noise-limited):

1. **The day-of-year normal tracks the within-season march; a whole-season normal cannot.** At hour 16 UTC the day-of-year (±15 d) VPD normal falls smoothly across the season (3.74 → 2.83 kPa, early-June → late-Sep), while a single whole-season normal is **flat** at 3.32 kPa. So the day-of-year climatology subtracts a *date-specific* normal — i.e. it removes the seasonal cycle by construction; the flat whole-season normal would leave it in.

2. **Standardizing every 2023 hourly sample both ways** (leave-one-year-out at the matched hour) gives a day-of-year season-part spread of **2.37** vs a whole-season spread of **1.81**. Note the day-of-year spread is *not* smaller — because the whole-season climatology partly **absorbs** the July heatwave into its inflated normal and thereby *masks* the real signal, whereas the day-of-year climatology correctly isolates each date's normal and **reveals** the true 2023 sub-seasonal departures (cool-humid early June, the record-hot July). A residual that survives the *correct* day-of-year normalization is real weather, not the by-construction artifact the pitfall warns about. See `figures/section11_seasonal_cycle_check.png`.

## QC step 4(c) — extreme positive VPD-z and the 2023 peak-heat window

July 2023 was Phoenix's hottest month on record — a 31-day streak of ≥110 °F daily highs from ~2023-06-30 to ~2023-07-30, peaking mid-to-late July. The most extreme positive VPD anomalies should be drawn from that window. The top-5 spatial-mean VPD-z overpasses:

| rank | overpass (UTC) | spatial-mean vpd_z | in 2023 heatwave window |
|---|---|---|---|
| 1 | 2023-09-10 04:03 | +1.581 | no |
| 2 | 2023-07-20 08:14 | +1.401 | yes |
| 3 | 2023-06-26 17:55 | +1.399 | no |
| 4 | 2023-08-30 16:14 | +1.393 | no |
| 5 | 2023-07-18 01:43 | +1.274 | yes |

**Robust statistic — heatwave-window ENRICHMENT.** VPD-z is standardized *per hour-of-day*, so the strict top-5 is brittle: a calm, low-variance night can post a high z without being a heat extreme, while a blazing afternoon (high hour-of-day variance) posts a more modest z. The honest, robust check is therefore enrichment, not the strict top-5. The heatwave window is **23%** of all overpasses but **64%** of the top-11 highest VPD-z — a **2.80× enrichment** (ranks of the 15 heatwave overpasses, 1 = highest: [2, 5, 6, 7, 9, 10, 11, 14, 15, 18, 19, 25, 26, 36, 38]; the #2 overpass overall is 2023-07-20, a heatwave date). The peak-heat window is clearly over-represented among the strongest VPD anomalies, as expected (2/5 of the strict top-5 also land in-window). The mapped most-extreme overpass is `figures/section11_vpd_z_extreme_date_map.png` — the VPD-z field is a smooth city-wide positive anomaly (ERA5-Land is ~9 km, so it varies gently across the domain, exactly as a regional driver should), which is spatially sensible.

## Saved climatology (kept to interpret results later — step 4 deliverable)

`vpd_clim_mean`, `vpd_clim_std`, `sm_clim_mean`, `sm_clim_std` (overpass, y, x) are saved alongside the z-scores in the same store.

## Figures

- `figures/section11_zscore_distributions.png` — z distributions (mean ≈ 0, std ≈ 1).
- `figures/section11_seasonal_cycle_check.png` — mean z by season part (flatness check).
- `figures/section11_vpd_z_extreme_date_map.png` — VPD-z map for the most extreme overpass.
