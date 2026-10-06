#!/usr/bin/env python3
"""plot_style — shared figure color convention (one source of truth for all sections).

Inputs : none (constants + lazy matplotlib helpers; import-light, no plotting stack needed to read names)
Outputs: CMAP / ACCENT / PIXEL_CLASS_* / LANDCOVER_COLORS tables + norm-builder helpers
Key decisions (full rationale in docs/DESIGN_DECISIONS.md):
  - Signed/anomaly fields: diverging cmap with white pinned at 0 (diverging_norm).
  - Vegetation: sequential greens; non-negative stress: white-at-0 reds.
  - Absolute temperature: warm sequential (inferno) — the one field with no white-at-0.
  - Demographic layers: neutral viridis (never a heat map) by design.
  - Categorical class fields: qualitative discrete palette + legend, never continuous.
Run: imported as a library (no CLI).
"""
from __future__ import annotations

# Colormap names by SEMANTIC ROLE (matplotlib registered names).
CMAP = {
    # signed / diverging (use with diverging_norm so WHITE sits at 0)
    "vpd_z": "RdBu_r",            # demand/dryness z: blue(-) - white(0) - red(+ drier = more stress)
    "moisture_z": "BrBG",        # sm_z supply / NDMI vegetation check: brown(- dry) - white(0) - green(+ wet)
    "cooling_advantage": "RdBu",  # ref-tree LST (K): red(- warmer) - white(0) - blue(+ cooler/benefit)
    "drought_pdsi": "BrBG",      # PDSI: brown(- drought) - white(0) - green(+ wet)
    "ndmi": "BrBG",              # NDMI moisture index: brown(dry) - white(0) - green(moist)
    # non-negative stress where 0 = none (sequential, white at 0)
    "stress": "Reds",            # CSI / demand_stress / supply_stress: white(0) -> dark red
    # vegetation / greenness (sequential greens; high = greener)
    "vegetation": "Greens",      # NDVI, canopy %, ESI
    # absolute temperature (sequential warm; 0 NOT meaningful -> no white@0)
    "temperature": "inferno",    # LST, tmean
    # other non-negative magnitudes
    "et": "YlGnBu",              # evapotranspiration flux (>=0): pale -> blue-green
    "impervious": "Greys",       # paved fraction %: white(0) -> dark(paved)
    "precip": "Blues",           # precipitation (>=0): white(0) -> dark blue
    "count": "YlGnBu",           # observation/usable counts (>=0)
    "demographic": "viridis",    # income / %POC / SVI -- NEUTRAL, never a heat map
}

# Single-hue ACCENT colors for 1-D plots (histograms / lines / scatter), echoing the map convention.
ACCENT = {
    "tree": "#1a7a3c",        # tree-dominated (green)
    "reference": "#8c6d46",   # built reference (earth brown)
    "cooling": "#1a9850",     # cooling advantage (green = benefit)
    "vpd": "#d7301f",         # VPD / demand (red)
    "moisture": "#2171b5",    # soil moisture (blue)
    "ndmi": "#238b45",        # NDMI / vegetation-condition check (green)
    "csi": "#6a51a3",         # compound stress (purple)
    "precip": "#2171b5",      # precipitation (blue)
    "neutral": "#4575b4",     # generic
    "zero_line": "#000000",   # the 0 reference line drawn on signed axes
}

# CATEGORICAL palettes (discrete + legend; NOT continuous colormaps).
# Section 10 paired-design pixel class raster (0=other, 1=tree, 2=reference).
PIXEL_CLASS_COLORS = {0: "#eef2ee", 1: "#1a7a3c", 2: "#c2a878"}
PIXEL_CLASS_LABELS = {0: "other", 1: "tree-dominated", 2: "built reference"}

# NLCD land-cover palette (subset present in the Phoenix domain); modules opt in.
LANDCOVER_COLORS = {
    11: "#476ba1",  # open water (blue)
    21: "#ddc9c9",  # developed open
    22: "#d89382",  # developed low
    23: "#ed0000",  # developed medium
    24: "#aa0000",  # developed high
    31: "#b3afa4",  # barren
    41: "#68aa63",  # deciduous forest
    42: "#1c6330",  # evergreen forest
    43: "#b5c98e",  # mixed forest
    52: "#ccba7c",  # shrub
    71: "#e3e3c2",  # grassland
    81: "#dcd939",  # pasture/hay
    82: "#ab6c28",  # cultivated crops
    90: "#b8d9eb",  # woody wetland
    95: "#6c9fb8",  # herbaceous wetland
}


# Normalization helpers (matplotlib imported lazily).
def diverging_norm(data=None, *, vcenter: float = 0.0, vmax: float | None = None,
                   symmetric: bool = True):
    """TwoSlopeNorm centred on vcenter so white lands exactly at the center (signed fields).

    symmetric=True shares one scale across both arms (vcenter ± max abs deviation);
    symmetric=False lets each arm use its own extent. vmax overrides the half-extent.
    """
    from matplotlib.colors import TwoSlopeNorm
    import numpy as np

    lo = hi = None
    if data is not None:
        a = np.asarray(data, dtype="float64")
        a = a[np.isfinite(a)]
        if a.size:
            lo = float(a.min())
            hi = float(a.max())
    if vmax is not None:
        m = float(abs(vmax))
        return TwoSlopeNorm(vmin=vcenter - m, vcenter=vcenter, vmax=vcenter + m)
    if symmetric:
        m = 1.0
        if lo is not None:
            m = max(abs(hi - vcenter), abs(lo - vcenter), 1e-6)
        return TwoSlopeNorm(vmin=vcenter - m, vcenter=vcenter, vmax=vcenter + m)
    # asymmetric to the data, white still exactly at vcenter
    vmin = (lo if lo is not None and lo < vcenter else vcenter - 1.0)
    vhi = (hi if hi is not None and hi > vcenter else vcenter + 1.0)
    return TwoSlopeNorm(vmin=vmin, vcenter=vcenter, vmax=vhi)


def sequential_norm(*, vmin: float = 0.0, vmax: float | None = None, data=None):
    """Plain Normalize for non-negative sequential fields; floor pinned at vmin (0) so white-at-0 ramps start blank."""
    from matplotlib.colors import Normalize
    import numpy as np

    if vmax is None and data is not None:
        a = np.asarray(data, dtype="float64")
        a = a[np.isfinite(a)]
        vmax = float(a.max()) if a.size else 1.0
    return Normalize(vmin=vmin, vmax=vmax)


def categorical_cmap(color_by_code: dict):
    """(ListedColormap, BoundaryNorm) for a discrete integer class field; legend built from the same dict."""
    from matplotlib.colors import ListedColormap, BoundaryNorm
    import numpy as np

    codes = sorted(color_by_code)
    colors = [color_by_code[c] for c in codes]
    cmap = ListedColormap(colors)
    bounds = [codes[0] - 0.5] + [c + 0.5 for c in codes]
    norm = BoundaryNorm(bounds, cmap.N)
    return cmap, norm
