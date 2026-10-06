#!/usr/bin/env python3
"""Section 3 / ECOSTRESS ET (PT-JPL) & ESI — acquire, screen, and cube supporting EO products.

Inputs : Earthdata CMR (ECO_L3T_JET v002, ECO_L4T_ESI v002) over the Section-2
         bbox/pilot window; data/raw/ecostress_{et,esi}/; the Section-1 70 m
         reference grid (config.REFERENCE_GRID_TIF).
Outputs: data/interim/ecostress_{et,esi}_cube (Zarr), per-product granule reports
         (CSV), overpass_links.parquet, and QA figures in config.FIGURES_DIR.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 3):
  - SUPPORTING evidence only — ET/ESI unreliable over built-up areas; restrict
    later use to high-tree-fraction pixels (Section 10).
  - PT-JPL ET = PTJPLSMinst layer of ECO_L3T_JET (Collection-1 name in protocol
    does not exist in v002); ESI/PET from ECO_L4T_ESI.
  - Pixel screening is exactly finite(value) AND cloud==0 AND water==0. No
    retrieval-quality QA bit/flag is downloaded or applied.
  - ETinstUncertainty is ensemble spread, not a retrieval-quality QA bit, and is
    not downloaded or used here.
  - Plausible ranges are advisory diagnostics only; values are never clipped.
  - Reuses Section 2 machinery (auth, manifest, clip, mask application, stats,
    and figures), while keeping this product-specific screening explicit.
  - Bilinear resample to 70 m (continuous quantities); overpass keys match LST.
Run: python src/section3_ecostress_et_esi.py [--max-granules N] [--skip-download]
     [--links-only] [--products et,esi] [--min-valid-fraction F] [-v]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import logging
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# Heavy geospatial / EO-access libraries (same set Section 2 uses). The pure
# logic below stays import-safe without the geo stack.
import earthaccess  # noqa: E402
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402

# Make config + the Section 2 module importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402
import section2_ecostress_lst as sec2  # noqa: E402  (reuse acquisition machinery)
import plot_style as ps  # noqa: E402  (shared figure color convention)

log = logging.getLogger("section3")

PROVIDER = "LPCLOUD"
PILOT_START, PILOT_END = config.PILOT_WINDOW

ANALYSIS_ROLE = "corroboration-only"
SCREENING_MASK = "isfinite(value) AND cloud == 0 AND water == 0"
RETRIEVAL_QUALITY_QA_FILTER = (
    "none; no retrieval-quality QA bit/flag band was downloaded or applied"
)
ADVISORY_RANGE_POLICY = (
    "diagnostic flag only; values outside the range are retained and never clipped"
)
ETINST_UNCERTAINTY_DISCLOSURE = (
    "unused; ETinstUncertainty is the standard deviation (ensemble spread) across "
    "the L3 JET ET estimates, not a retrieval-quality QA bit"
)


# --- Product configuration (pure data; no geo deps) ----------------------------
@dataclasses.dataclass(frozen=True)
class Product:
    """One ECOSTRESS tiled product to acquire. measure_layers[0] is primary
    (drives the drop/coverage decision); download_layers = measures + gates."""

    key: str                       # short id used in paths/figures ("et"/"esi")
    short_name: str
    version: str
    doi: str
    raw_subdir: str                # data/raw/<raw_subdir>/
    cube_dirname: str              # data/interim/<cube_dirname> (zarr)
    measure_layers: tuple          # band file suffixes kept as data variables
    gate_layers: tuple             # mask layers (cloud, water)
    var_names: dict                # layer-suffix -> cube variable name
    var_units: dict                # cube variable name -> units string
    var_long_names: dict           # cube variable name -> long_name
    plausible: dict                # primary variable -> (lo, hi), flag-only range

    @property
    def dataset_id(self) -> str:
        return f"{self.short_name}.{self.version}"

    @property
    def download_layers(self) -> tuple:
        return tuple(self.measure_layers) + tuple(self.gate_layers)

    @property
    def primary_layer(self) -> str:
        return self.measure_layers[0]

    @property
    def primary_var(self) -> str:
        return self.var_names[self.primary_layer]


# ET: PT-JPL instantaneous evapotranspiration from the Joint-ET tile.
ET_PRODUCT = Product(
    key="et",
    short_name="ECO_L3T_JET",
    version="002",
    doi="10.5067/ECOSTRESS/ECO_L3T_JET.002",
    raw_subdir="ecostress_et",
    cube_dirname="ecostress_et_cube",
    measure_layers=("PTJPLSMinst",),
    gate_layers=("cloud", "water"),
    var_names={"PTJPLSMinst": "et"},
    var_units={"et": "W m-2"},
    var_long_names={
        "et": "ECOSTRESS PT-JPL(-SM) instantaneous evapotranspiration "
              "(screened: isfinite(value) AND cloud == 0 AND water == 0; "
              "ECO_L3T_JET PTJPLSMinst; corroboration only)"
    },
    # Advisory window only; negatives are retrieval noise, flagged not dropped.
    plausible={"et": (0.0, 900.0)},
)

# ESI: evaporative stress index + potential ET from the L4T ESI tile.
ESI_PRODUCT = Product(
    key="esi",
    short_name="ECO_L4T_ESI",
    version="002",
    doi="10.5067/ECOSTRESS/ECO_L4T_ESI.002",
    raw_subdir="ecostress_esi",
    cube_dirname="ecostress_esi_cube",
    measure_layers=("ESI", "PET"),
    gate_layers=("cloud", "water"),
    var_names={"ESI": "esi", "PET": "pet"},
    var_units={"esi": "1", "pet": "W m-2"},
    var_long_names={
        "esi": "ECOSTRESS evaporative stress index (screened: isfinite(value) "
               "AND cloud == 0 AND water == 0; ECO_L4T_ESI, dimensionless "
               "ET/PET; corroboration only)",
        "pet": "ECOSTRESS potential evapotranspiration (screened: "
               "isfinite(value) AND cloud == 0 AND water == 0; ECO_L4T_ESI "
               "PET; corroboration only)",
    },
    plausible={"esi": (0.0, 1.0)},
)

PRODUCTS = {ET_PRODUCT.key: ET_PRODUCT, ESI_PRODUCT.key: ESI_PRODUCT}

DEFAULT_MIN_VALID_FRACTION = sec2.DEFAULT_MIN_VALID_FRACTION


def supporting_keep_mask(
    values: np.ndarray, cloud: np.ndarray, water: np.ndarray
) -> np.ndarray:
    """Return the exact Section-3 screening mask; no retrieval QA is implied."""
    finite = np.isfinite(np.asarray(values, dtype="float64"))
    clear = np.asarray(cloud) == 0
    land = np.asarray(water) == 0
    return finite & clear & land


def variable_disclosure_attrs(product: Product, variable: str) -> dict:
    """Metadata that makes screening, role, and range handling auditable."""
    attrs = {
        "analysis_role": ANALYSIS_ROLE,
        "screening_mask": SCREENING_MASK,
        "cloud_mask_keep_condition": "cloud == 0 (clear)",
        "water_mask_keep_condition": "water == 0 (land/non-water)",
        "finite_value_keep_condition": "isfinite(value)",
        "retrieval_quality_qa_filter_applied": False,
        "retrieval_quality_qa_filter": RETRIEVAL_QUALITY_QA_FILTER,
        "advisory_range_policy": ADVISORY_RANGE_POLICY,
        "etinst_uncertainty_used": False,
        "etinst_uncertainty_disclosure": ETINST_UNCERTAINTY_DISCLOSURE,
    }
    advisory = product.plausible.get(variable)
    attrs["advisory_range_defined"] = advisory is not None
    if advisory is None:
        attrs["advisory_range"] = "none configured"
    else:
        attrs["advisory_range_min"] = float(advisory[0])
        attrs["advisory_range_max"] = float(advisory[1])
        attrs["advisory_range_units"] = product.var_units[variable]
    return attrs


def dataset_disclosure_attrs(product: Product) -> dict:
    """Dataset-level copy of the Section-3 screening and interpretation contract."""
    lo, hi = product.plausible[product.primary_var]
    return {
        "analysis_role": ANALYSIS_ROLE,
        "screening_mask": SCREENING_MASK,
        "cloud_mask_keep_condition": "cloud == 0 (clear)",
        "water_mask_keep_condition": "water == 0 (land/non-water)",
        "finite_value_keep_condition": "isfinite(value)",
        "retrieval_quality_qa_filter_applied": False,
        "retrieval_quality_qa_filter": RETRIEVAL_QUALITY_QA_FILTER,
        "primary_variable_advisory_range": (
            f"{product.primary_var}: {lo:g} to {hi:g} {product.var_units[product.primary_var]}"
        ),
        "advisory_range_policy": ADVISORY_RANGE_POLICY,
        "etinst_uncertainty_used": False,
        "etinst_uncertainty_disclosure": ETINST_UNCERTAINTY_DISCLOSURE,
        "qc_documentation": "docs/section3_et_esi_qc_note.md",
    }


# --- Filename parsing (pure; generalises Section 2's LSTE-only parser) ---------
# ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif
#   sensor _level _param _orbit _scene _tile _YYYYMMDDTHHMMSS _build _iter _LAYER
# JET layer names are alphanumeric (e.g. PTJPLSMinst), so this pattern allows
# digits in the layer where Section 2's LSTE-only regex forbade them.
_GRANULE_RE = re.compile(
    r"^(?P<sensor>ECOv\d{3})_(?P<level>L\d[TG])_(?P<param>[A-Za-z0-9-]+?)_"
    r"(?P<orbit>\d+)_(?P<scene>\d+)_(?P<tile>[0-9A-Z]+)_"
    r"(?P<dt>\d{8}T\d{6})_(?P<build>\d+)_(?P<iter>\d+)_(?P<layer>[A-Za-z0-9]+)\.tif$"
)


def parse_granule_filename(filename: str) -> "sec2.GranuleFile":
    """Parse an ECOSTRESS tiled COG filename into Section 2's GranuleFile, giving
    overpass_key (orbit_scene_timestamp) identical in form to the Section-2 keys."""
    name = Path(filename).name
    m = _GRANULE_RE.match(name)
    if not m:
        raise ValueError(f"Not an ECOSTRESS tiled COG filename: {name!r}")
    g = m.groupdict()
    dt = _dt.datetime.strptime(g["dt"], "%Y%m%dT%H%M%S").replace(
        tzinfo=_dt.timezone.utc
    )
    return sec2.GranuleFile(
        filename=name,
        sensor=g["sensor"],
        orbit=g["orbit"],
        scene=g["scene"],
        tile=g["tile"],
        datetime_utc=dt,
        build=g["build"],
        iteration=g["iter"],
        layer=g["layer"],
    )


def sibling_layer_path(primary_path: Path, layer: str) -> Path:
    """Given a ..._<LAYER>.tif path, return the sibling path for another layer."""
    return primary_path.with_name(
        re.sub(r"_[A-Za-z0-9]+\.tif$", f"_{layer}.tif", primary_path.name)
    )


def discover_local_primary_files(raw_dir: Path, primary_layer: str) -> list[Path]:
    """All ..._<primary_layer>.tif COGs already present locally (--skip-download)."""
    return sorted(raw_dir.glob(f"ECOv*_*_{primary_layer}.tif"))


# --- Earthdata search + download (step 19; reuses Section 2 helpers) -----------
def search_product(product: Product, max_granules: int | None = None):
    """Search one product over the SAME bbox / pilot window as Section 2."""
    bbox = sec2.bbox_for_earthaccess()
    log.info(
        "Searching CMR: short_name=%s version=%s provider=%s bbox=%s temporal=%s",
        product.short_name, product.version, PROVIDER, bbox, (PILOT_START, PILOT_END),
    )
    results = earthaccess.search_data(
        short_name=product.short_name,
        version=product.version,
        provider=PROVIDER,
        bounding_box=bbox,
        temporal=(PILOT_START, PILOT_END),
        count=2000 if max_granules is None else max_granules,
    )
    log.info("CMR returned %d granule(s) for %s", len(results), product.short_name)
    if max_granules is not None:
        results = results[:max_granules]
    return results


def needed_layer_links(results, product: Product) -> list[str]:
    """Download URLs for only this product's needed layers (keeps data/raw small)."""
    suffixes = tuple(f"_{lyr}.tif" for lyr in product.download_layers)
    seen, unique = set(), []
    for granule in results:
        for url in granule.data_links():
            if url.endswith(suffixes) and url not in seen:
                seen.add(url)
                unique.append(url)
    return unique


def download_product(results, product: Product, raw_dir: Path) -> list[Path]:
    """Download needed COGs into data/raw/<subdir>/ and record them in the manifest
    (Section 2's exact schema and de-duplicating appender)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    urls = needed_layer_links(results, product)
    log.info("Downloading %d COG(s) into %s", len(urls), raw_dir)
    local = earthaccess.download(urls, str(raw_dir))
    paths = [Path(p) for p in local if str(p).endswith(".tif")]

    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    url_by_name = {u.rsplit("/", 1)[-1]: u for u in urls}
    rows = [{
        "source": url_by_name.get(p.name, f"NASA LP DAAC ({PROVIDER})"),
        "dataset": product.dataset_id,
        "filename": p.name,
        "download_date": today,
        "checksum": f"sha256:{sec2.sha256_file(p)}",
    } for p in paths]
    sec2.append_to_manifest(rows)
    return paths


# --- Per-granule cleaning (steps 20-21; needs the geo stack at run time) -------
def clean_tile(primary_path: Path, product: Product, reference,
               min_valid_fraction: float):
    """Read, apply the disclosed screening mask, and reproject one granule tile.

    Returns (aligned_dataset_or_None, GranuleStats); the dataset is None when the
    granule is dropped as near-empty. Drop/coverage stats use the PRIMARY layer."""
    gf = parse_granule_filename(primary_path.name)

    cloud = sec2._open_raw(sibling_layer_path(primary_path, "cloud"), mask_and_scale=False)
    water = sec2._open_raw(sibling_layer_path(primary_path, "water"), mask_and_scale=False)
    cloud = sec2._clip_to_bbox(cloud)
    water = sec2._clip_to_bbox(water)

    measures = {}
    for layer in product.measure_layers:
        da = sec2._open_raw(sibling_layer_path(primary_path, layer), mask_and_scale=True)
        measures[layer] = sec2._clip_to_bbox(da)

    primary = measures[product.primary_layer]
    keep_primary = supporting_keep_mask(primary.values, cloud.values, water.values)

    primary_clean = sec2.apply_keep_mask(primary.values, keep_primary)
    stats = sec2.summarize_granule(
        primary_clean, gf.overpass_key, gf.datetime_utc, gf.tile,
        plausible_k=product.plausible[product.primary_var],
    )
    if sec2.decide_drop(stats, min_valid_fraction):
        stats.dropped = True
        log.warning("DROP  %s tile=%s %s -- valid_fraction=%.4f < %.4f (near-empty)",
                    gf.overpass_key, gf.tile, product.key,
                    stats.valid_fraction, min_valid_fraction)
        return None, stats
    stats.range_flagged = sec2.decide_range_flag(
        stats, plausible_k=product.plausible[product.primary_var])
    if stats.range_flagged:
        lo, hi = product.plausible[product.primary_var]
        log.warning("FLAG  %s tile=%s %s -- %s outside %.1f-%.1f (min=%.2f max=%.2f) -- kept",
                    gf.overpass_key, gf.tile, product.key, product.primary_var,
                    lo, hi, stats.lst_min, stats.lst_max)

    # Bilinear resample every measure layer onto the 70 m grid (continuous).
    data_vars = {}
    for layer, da in measures.items():
        keep = supporting_keep_mask(da.values, cloud.values, water.values)
        clean = sec2.apply_keep_mask(da.values, keep)
        clean_da = da.copy(data=clean)
        aligned = clean_da.rio.reproject_match(reference, resampling=Resampling.bilinear)
        aligned = aligned.rio.write_nodata(np.nan, encoded=False)
        data_vars[product.var_names[layer]] = aligned
    ds = xr.Dataset(data_vars)
    return ds, stats


# --- Build + save the cube (step 21) ------------------------------------------
def build_cube(primary_files: Iterable[Path], product: Product, reference,
               min_valid_fraction: float) -> tuple["xr.Dataset", pd.DataFrame]:
    """Clean every granule, mosaic tiles within an overpass, stack by time.

    Returns (cube_dataset, granule_report). Values are NEVER averaged across
    DIFFERENT overpasses (overpass local times differ — same caveat as Section 2)."""
    per_overpass: dict[str, dict] = {}
    report_rows: list[dict] = []

    for path in primary_files:
        aligned, stats = clean_tile(path, product, reference, min_valid_fraction)
        report_rows.append(stats.as_row())
        if aligned is None:
            continue
        slot = per_overpass.setdefault(
            stats.overpass_key, {"time": stats.datetime_utc, "tiles": []})
        slot["tiles"].append(aligned)

    if not per_overpass:
        raise RuntimeError(f"No {product.key} granules survived screening -- nothing to stack.")

    var_list = [product.var_names[l] for l in product.measure_layers]
    times, slices, keys, orbits, scenes = [], [], [], [], []
    for key in sorted(per_overpass, key=lambda k: per_overpass[k]["time"]):
        info = per_overpass[key]
        merged = info["tiles"][0]
        for extra in info["tiles"][1:]:
            # Fill gaps in each variable from sibling tiles of the same overpass.
            merged = merged.copy()
            for v in var_list:
                merged[v] = merged[v].where(np.isfinite(merged[v]), extra[v])
        times.append(np.datetime64(info["time"].replace(tzinfo=None), "ns"))
        slices.append(merged)
        orbit, scene, _ = key.split("_")
        keys.append(key)
        orbits.append(orbit)
        scenes.append(scene)

    cube = xr.concat(slices, dim="time")
    cube = cube.assign_coords(
        time=("time", np.array(times)),
        overpass_key=("time", np.array(keys)),
        orbit=("time", np.array(orbits)),
        scene=("time", np.array(scenes)),
    ).sortby("time")

    for layer in product.measure_layers:
        v = product.var_names[layer]
        cube[v].attrs.update(
            long_name=product.var_long_names[v],
            units=product.var_units[v],
            **variable_disclosure_attrs(product, v),
        )
    cube.attrs.update(
        dataset=product.dataset_id, doi=product.doi,
        note=("Per-overpass ECOSTRESS %s on the Section-1 70 m grid. SUPPORTING "
              "evidence only -- unreliable over built-up areas; restrict to "
              "high-tree-fraction pixels (Section 10). Time axis preserved; not "
              "averaged across overpasses. See Section 3 of the protocol."
              % product.key.upper()),
        **dataset_disclosure_attrs(product),
    )
    cube = cube.rio.write_crs(config.CRS)
    return cube, pd.DataFrame(report_rows)


def save_cube_zarr(cube: "xr.Dataset", product: Product, interim_dir: Path) -> Path:
    """Save the cube dataset to data/interim/<cube_dirname> as Zarr."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    out = interim_dir / product.cube_dirname
    cube.to_zarr(out, mode="w", consolidated=True)
    log.info("Saved %s cube -> %s  dims=%s", product.key, out, dict(cube.sizes))
    return out


# --- Overpass-link table (step 22) --------------------------------------------
def _overpass_keys_from_cube(cube_dir: Path) -> dict[str, dict]:
    """Read {overpass_key -> {datetime_utc, orbit, scene}} from a saved cube
    (LST or ET/ESI); key reconstructed as GranuleFile does: orbit_scene_%Y%m%dT%H%M%S."""
    if not cube_dir.exists():
        return {}
    ds = xr.open_zarr(cube_dir)
    out: dict[str, dict] = {}
    orbits = [str(o) for o in ds["orbit"].values]
    scenes = [str(s) for s in ds["scene"].values]
    times = pd.to_datetime(ds["time"].values)
    for orbit, scene, t in zip(orbits, scenes, times):
        key = f"{orbit}_{scene}_{t.strftime('%Y%m%dT%H%M%S')}"
        out[key] = {"datetime_utc": t.isoformat(), "orbit": orbit, "scene": scene}
    ds.close()
    return out


def assemble_links(lst: dict, et: dict, esi: dict) -> pd.DataFrame:
    """Pure assembly of the overpass-link table from three {key -> meta} dicts:
    one row per overpass in ANY of LST/ET/ESI, with membership and pairing flags.
    Separated from disk I/O so it is unit-testable without the geo stack."""
    rows = []
    for key in sorted(set(lst) | set(et) | set(esi)):
        meta = lst.get(key) or et.get(key) or esi.get(key)
        in_lst, in_et, in_esi = key in lst, key in et, key in esi
        rows.append({
            "overpass_key": key,
            "datetime_utc": meta["datetime_utc"],
            "orbit": meta["orbit"],
            "scene": meta["scene"],
            "in_lst": in_lst,
            "in_et": in_et,
            "in_esi": in_esi,
            "et_paired_to_lst": in_lst and in_et,
            "esi_paired_to_lst": in_lst and in_esi,
        })
    cols = ["overpass_key", "datetime_utc", "orbit", "scene",
            "in_lst", "in_et", "in_esi", "et_paired_to_lst", "esi_paired_to_lst"]
    df = pd.DataFrame(rows, columns=cols)
    if len(df):
        df = df.sort_values("datetime_utc").reset_index(drop=True)
    return df


def build_overpass_links(interim_dir: Path) -> pd.DataFrame:
    """Assemble the overpass-link table keyed to the Section-2 LST overpasses
    (reads the saved LST/ET/ESI cubes, then delegates to assemble_links)."""
    lst = _overpass_keys_from_cube(config.INTERIM_DIR / sec2.CUBE_DIRNAME)
    et = _overpass_keys_from_cube(interim_dir / ET_PRODUCT.cube_dirname)
    esi = _overpass_keys_from_cube(interim_dir / ESI_PRODUCT.cube_dirname)
    return assemble_links(lst, et, esi)


def save_overpass_links(df: pd.DataFrame, interim_dir: Path) -> Path:
    out = interim_dir / "overpass_links.parquet"
    df.to_parquet(out, index=False)
    n_et = int(df["et_paired_to_lst"].sum()) if len(df) else 0
    n_esi = int(df["esi_paired_to_lst"].sum()) if len(df) else 0
    log.info("Overpass links -> %s  (%d rows; %d ET-LST, %d ESI-LST pairings)",
             out, len(df), n_et, n_esi)
    return out


# --- Figures (usable-obs count + mean map per product) ------------------------
def make_figures(cube: "xr.Dataset", product: Product, figures_dir: Path) -> list[Path]:
    """Write per-pixel usable-observation count and a mean map of the primary var."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    var = product.primary_var
    stack = cube[var].values  # (time, y, x)
    count = sec2.usable_observation_count(stack)
    mean = sec2.mean_lst_map(stack)  # generic per-pixel nanmean (reused)

    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    outputs = []

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(count, extent=extent, origin="upper", cmap="viridis")
    ax.set_title(f"ECOSTRESS {product.key.upper()} usable observations per pixel\n"
                 f"Phoenix {PILOT_START}..{PILOT_END}  (n_overpass={cube.sizes['time']})")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m, EPSG:32612)")
    fig.colorbar(im, ax=ax, label="count of usable overpasses")
    p1 = figures_dir / f"ecostress_{product.key}_usable_count.png"
    fig.savefig(p1, dpi=150, bbox_inches="tight"); plt.close(fig); outputs.append(p1)

    fig, ax = plt.subplots(figsize=(7, 6))
    # ESI is a vegetation-vigor index (sequential greens); ET is a water flux (blue-green).
    mean_cmap = ps.CMAP["vegetation"] if product.key == "esi" else ps.CMAP["et"]
    im = ax.imshow(mean, extent=extent, origin="upper", cmap=mean_cmap)
    ax.set_title(f"ECOSTRESS mean {var} ({product.var_units[var]}) -- visual QA only\n"
                 f"Phoenix {PILOT_START}..{PILOT_END} (supporting evidence; built-up "
                 f"pixels unreliable)")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m, EPSG:32612)")
    fig.colorbar(im, ax=ax, label=f"mean {var} ({product.var_units[var]})")
    p2 = figures_dir / f"ecostress_{product.key}_mean_map.png"
    fig.savefig(p2, dpi=150, bbox_inches="tight"); plt.close(fig); outputs.append(p2)

    log.info("Wrote %s figures: %s", product.key, ", ".join(p.name for p in outputs))
    return outputs


# --- Orchestration / CLI ------------------------------------------------------
def process_product(product: Product, reference, max_granules, skip_download,
                    min_valid_fraction) -> "xr.Dataset":
    raw_dir = config.RAW_DIR / product.raw_subdir
    raw_dir.mkdir(parents=True, exist_ok=True)

    if skip_download:
        primary_files = discover_local_primary_files(raw_dir, product.primary_layer)
        log.info("--skip-download: found %d local %s COG(s)", len(primary_files), product.key)
        if not primary_files:
            raise SystemExit(f"No local {product.key} granules in {raw_dir}; "
                             "run without --skip-download.")
    else:
        results = search_product(product, max_granules=max_granules)
        if not results:
            raise SystemExit(f"CMR search returned no {product.key} granules.")
        download_product(results, product, raw_dir)
        primary_files = discover_local_primary_files(raw_dir, product.primary_layer)

    log.warning(
        "%s screening disclosure: mask=%s. Retrieval-quality QA filter=%s. "
        "Range policy=%s. %s.",
        product.key.upper(), SCREENING_MASK, RETRIEVAL_QUALITY_QA_FILTER,
        ADVISORY_RANGE_POLICY, ETINST_UNCERTAINTY_DISCLOSURE,
    )

    cube, report = build_cube(primary_files, product, reference, min_valid_fraction)
    save_cube_zarr(cube, product, config.INTERIM_DIR)

    report_path = config.INTERIM_DIR / f"ecostress_{product.key}_granule_report.csv"
    report.to_csv(report_path, index=False)
    n_drop = int(report["dropped"].sum()) if len(report) else 0
    n_flag = int(report["range_flagged"].sum()) if len(report) else 0
    log.info("%s granule report -> %s  (%d dropped, %d range-flagged of %d tiles)",
             product.key, report_path, n_drop, n_flag, len(report))

    make_figures(cube, product, config.FIGURES_DIR)
    return cube


def run(max_granules=None, skip_download=False, links_only=False,
        min_valid_fraction=DEFAULT_MIN_VALID_FRACTION, products=("et", "esi")) -> None:
    config.ensure_dirs()

    if not links_only:
        if not skip_download:
            sec2.authenticate()  # step 19 (reused)
        reference = rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)
        for key in products:
            process_product(PRODUCTS[key], reference, max_granules, skip_download,
                            min_valid_fraction)

    # Step 22 -- overpass-link table keyed to the Section-2 LST overpasses.
    links = build_overpass_links(config.INTERIM_DIR)
    save_overpass_links(links, config.INTERIM_DIR)
    log.info("Section 3 complete.")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 3 - ECOSTRESS ET (PT-JPL) & ESI acquisition and screening."
    )
    p.add_argument("--max-granules", type=int, default=None,
                   help="cap granules per product (quick smoke test).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse COGs already in data/raw/ecostress_{et,esi}/.")
    p.add_argument("--links-only", action="store_true",
                   help="rebuild only the overpass-link table from existing cubes.")
    p.add_argument("--products", default="et,esi",
                   help="comma list of products to process (default et,esi).")
    p.add_argument("--min-valid-fraction", type=float, default=DEFAULT_MIN_VALID_FRACTION,
                   help="drop a granule if fewer than this fraction of study-area "
                        "pixels survive QC (default %(default)s).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(
        max_granules=args.max_granules,
        skip_download=args.skip_download,
        links_only=args.links_only,
        min_valid_fraction=args.min_valid_fraction,
        products=tuple(s.strip() for s in args.products.split(",") if s.strip()),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
