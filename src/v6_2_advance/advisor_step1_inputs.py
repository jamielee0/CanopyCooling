"""Nonthermal transformations for the October 2026 advisor's Section 7 Step 1."""
import base64
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from .results_packet import solar_times
from .step6_inputs import brackets, solar_geometry, timestamp

QA_ORDER = {"best": 0, "good": 1, "suspect": 2, "poor": 3}
OTHER_YEAR_ORBITS = {6281, 6510, 33496, 33623, 40111, 40192, 40376}
OTHER_YEAR_METADATA = (
    "orbit", "acquisition_utc", "local_date", "year", "month", "solar_hour",
    "l1b_view_zenith_abs_p95_deg", "l1b_geometry_coverage_fraction",
)
EFFECT_COLUMNS = (
    "cooling_K_per_10pp", "gradient_K_per_10pp", "temperature_slope_K_per_canopy_fraction",
    "cooling_q025_1km", "cooling_q975_1km", "cooling_q025_2km", "cooling_q975_2km",
    "cooling_q025_4km", "cooling_q975_4km", "cooling_q025_8km", "cooling_q975_8km",
    "equivalent_point_8km", "equivalent_q025_8km", "equivalent_q975_8km",
    "difference_8km", "difference_q025_8km", "difference_q975_8km",
)


def hash_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_other_year_metadata(path, columns=OTHER_YEAR_METADATA):
    """Decode only the explicitly approved nonthermal selection columns."""
    if not set(columns).issubset(OTHER_YEAR_METADATA):
        raise ValueError("Unapproved other-year input column")
    return pd.read_csv(path, usecols=list(columns), dtype=str).fillna("").to_dict("records")


def exact_geo_flag(xml_bytes, expected_granule):
    root = ET.fromstring(xml_bytes)
    if expected_granule not in root.attrib.get("name", ""):
        raise ValueError("GEO metadata granule identity mismatch")
    groups = [e for e in root.iter() if e.tag.endswith("}Group") and e.attrib.get("name") == "L1GEOMetadata"]
    fields = [e for g in groups for e in g if e.attrib.get("name") == "GeolocationAccuracyQA"]
    if len(fields) != 1:
        raise ValueError("Missing or ambiguous exact GEO quality field")
    values = [e.text for e in fields[0] if e.tag.endswith("}compact")]
    if len(values) != 1:
        raise ValueError("GEO quality is not an inline metadata value")
    raw = base64.b64decode(values[0].strip(), validate=True).decode("utf-8").strip("\x00 \n\t")
    normalized = raw.lower()
    if normalized not in QA_ORDER:
        raise ValueError("Unknown GEO quality category")
    return raw, normalized


def scene_summary(rows):
    keys = [r["scene_key"] for r in rows]
    if not rows or len(keys) != len(set(keys)):
        raise ValueError("Empty or duplicate per-pass scenes")
    flags = {r["scene_key"]: r["category"] for r in sorted(rows, key=lambda r: r["scene_key"])}
    if not set(flags.values()).issubset(QA_ORDER):
        raise ValueError("Unrecognized scene quality")
    unique = sorted(set(flags.values()), key=QA_ORDER.get)
    return {
        "geolocation_categories_by_scene": json.dumps(flags, sort_keys=True, separators=(",", ":")),
        "geolocation_categories": ";".join(unique),
        "geolocation_worst_category": max(unique, key=QA_ORDER.get),
        "n_source_scenes": len(rows),
        **{f"geo_{name}_scene_count": sum(v == name for v in flags.values()) for name in QA_ORDER},
        "all_scene_categories_census_usable": all(v in ("best", "good") for v in flags.values()),
    }


def sun_at(utc, latitude, longitude):
    t = timestamp(utc)
    mean, apparent, eot = solar_times(t.to_pydatetime(), longitude)
    year_length = datetime(t.year, 12, 31).timetuple().tm_yday
    zenith, azimuth = solar_geometry(latitude, apparent, t.dayofyear, days_in_year=year_length)
    cosine = float(np.cos(np.deg2rad(zenith)))
    return dict(mean_solar_hour=mean, apparent_solar_hour=apparent,
                equation_of_time_min=eot, solar_zenith_deg=zenith,
                solar_elevation_deg=90.0-zenith, sin_solar_elevation=cosine,
                solar_azimuth_deg=azimuth, days_in_year=year_length)


def interpolate_shortwave(sw0, sw1, cosine0, cosine1, cosine_at, weight):
    """Advisor's ratio interpolation, with the stated low-sun rule only."""
    values = np.asarray([sw0, sw1, cosine0, cosine1, cosine_at, weight], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Missing or nonfinite shortwave interpolation input")
    if min(sw0, sw1) < 0 or not 0 <= weight <= 1:
        raise ValueError("Negative radiation or invalid temporal weight")
    if not all(-1 <= c <= 1 for c in (cosine0, cosine1, cosine_at)) or cosine_at <= 0:
        raise ValueError("Invalid or below-horizon solar geometry")
    use0, use1 = cosine0 >= 0.1, cosine1 >= 0.1
    if not use0 and not use1:
        raise ValueError("Both hourly cosines below 0.1; advisor clarification required")
    r0 = sw0 / cosine0 if use0 else None
    r1 = sw1 / cosine1 if use1 else None
    if use0 and use1:
        ratio, method = (1-weight)*r0 + weight*r1, "interpolated_hourly_sw_over_cosine"
    elif use0:
        ratio, method = r0, "floor_ratio_only_ceiling_cosine_below_0p1"
    else:
        ratio, method = r1, "ceiling_ratio_only_floor_cosine_below_0p1"
    return dict(shortwave_W_m2=float(ratio*cosine_at), shortwave_interpolation_method=method,
                shortwave_floor_normalized=r0, shortwave_ceiling_normalized=r1)


def check_holdout_blanks(rows):
    selected = [r for r in rows if int(r["orbit"]) in OTHER_YEAR_ORBITS and r["city"] == "phoenix"]
    if len(selected) != 7 or {int(r["orbit"]) for r in selected} != OTHER_YEAR_ORBITS:
        raise ValueError("Other-year pass identities changed")
    for row in selected:
        for column in EFFECT_COLUMNS:
            value = row.get(column)
            if value not in (None, "") and not (isinstance(value, float) and math.isnan(value)):
                raise ValueError("Other-year effect value would be disclosed")
    return True
