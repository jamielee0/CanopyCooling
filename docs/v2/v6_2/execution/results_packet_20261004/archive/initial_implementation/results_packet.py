"""Read-only assembly rules for released pass estimates; no fitting or unsealing."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

SIZES = (1, 2, 4, 8)
MODEL_VARIANTS = {1: "paired_primary", 2: "spatial_2km", 4: "spatial_4km", 8: "spatial_8km"}
SEALED_FIELDS = (
    "signed_flux_change_W_m2_per_10pp", "flux_reduction_W_m2_per_10pp",
    "signed_equivalent_change_K_per_10pp", "equivalent_cooling_K_per_10pp",
)


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256")
    return digest.hexdigest()


def number(value, *, required=True):
    if value is None or str(value).strip().lower() in ("", "nan", "none", "null"):
        if required:
            raise ValueError("Required numeric value missing")
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric value")
    return result


def integer(value):
    result = number(value)
    if result != int(result):
        raise ValueError("Integer field is fractional")
    return int(result)


def timestamp(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Acquisition time must be timezone-aware")
    return t.astimezone(timezone.utc)


def solar_times(t: datetime, longitude_deg: float):
    """NOAA-style harmonic EOT used by repository audit, retaining subseconds.

    Longitude is east-positive. This is a clock convention, not a new time model.
    """
    if t.tzinfo is None:
        raise ValueError("Solar time requires timezone-aware acquisition")
    if not -180 <= longitude_deg <= 180:
        raise ValueError("Invalid longitude")
    t = t.astimezone(timezone.utc)
    hour = t.hour + t.minute / 60 + (t.second + t.microsecond / 1e6) / 3600
    days = datetime(t.year, 12, 31).timetuple().tm_yday
    gamma = 2 * math.pi / days * (t.timetuple().tm_yday - 1 + (hour - 12) / 24)
    eot = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                    - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    mean = (hour + longitude_deg / 15) % 24
    return mean, (mean + eot / 60) % 24, eot


def keyed(rows, fields):
    result = {}
    for row in rows:
        key = tuple(str(row[field]) for field in fields)
        if key in result:
            raise ValueError(f"Duplicate identity: {key}")
        result[key] = row
    return result


def reconcile_estimate(row, precision, size):
    """Validate independent released point/precision records, then select interval."""
    gradient = number(row["gradient_K_per_10pp"])
    cooling = number(row["cooling_K_per_10pp"])
    if not math.isclose(gradient, -cooling, rel_tol=0, abs_tol=1e-12):
        raise ValueError("Signed temperature change and cooling disagree")
    se = number(row[f"SE_{size}km_K_per_10pp"])
    low = number(row[f"cooling_q025_{size}km"])
    high = number(row[f"cooling_q975_{size}km"])
    if low > high or se < 0:
        raise ValueError("Invalid interval or SE")
    if not math.isclose(se, number(precision["LST_K_SE_per_10pp"]), rel_tol=0, abs_tol=1e-12):
        raise ValueError("Released SE and public precision do not reconcile")
    if not math.isclose(high - low, number(precision["LST_K_bootstrap_width_95_per_10pp"]),
                        rel_tol=0, abs_tol=1e-12):
        raise ValueError("Released interval and public precision width do not reconcile")
    requested = integer(precision["bootstrap_requested"])
    estimable = integer(precision["bootstrap_estimable"])
    failed = integer(precision["bootstrap_failed"])
    if requested != estimable + failed or min(requested, estimable, failed) < 0 or estimable < 2:
        raise ValueError("Invalid bootstrap accounting")
    if any(integer(row[k]) != integer(precision[k]) for k in ("n_cells", "n_blocks")):
        raise ValueError("Spatial sensitivity changes the fitted population")
    return gradient, cooling, se, low, high


def footprint_area_km2(audit_rows, expected_cells):
    """Sum retained whole cells once per canonical tile; do not multiply by scenes."""
    if not audit_rows:
        raise ValueError("Missing ownership audit")
    keyed(audit_rows, ("city", "tile"))
    total = 0
    area = 0.0
    for row in audit_rows:
        count = integer(row["paired_complete_primary"])
        if count < 0 or count > integer(row["unique_QA_valid_before_context"]):
            raise ValueError("Invalid retained native-cell count")
        if row["ownership"] != "whole_footprint_inside_canonical_core_and_UTM_band":
            raise ValueError("Unverified canonical ground ownership")
        cell_area = number(row["native_area_m2"])
        if cell_area != 4900:
            raise ValueError("Expected frozen 70 m native-cell footprint")
        total += count
        area += count * cell_area
    if total != expected_cells:
        raise ValueError("Ownership count does not equal released model count")
    return area / 1e6


def support_quantiles(support, row):
    if any(integer(support[k]) != integer(row[k]) for k in ("n_cells", "n_blocks")):
        raise ValueError("Predictor snapshot and released fit support disagree")
    q = {key: number(value) for key, value in support["quantiles"].items()}
    ordered = [q[k] for k in sorted(q, key=float)]
    if not ordered or min(ordered) < 0 or max(ordered) > 1 or ordered != sorted(ordered):
        raise ValueError("Canopy fraction quantiles are invalid")
    return q


def validate_weather(row, weather, hourly):
    """Cross-check cached interpolation; do not fill gaps or treat VPD as a control."""
    t = timestamp(row["acquisition_utc"])
    if timestamp(weather["acquisition_utc"]) != t:
        raise ValueError("Weather acquisition identity mismatch")
    h0 = t.replace(minute=0, second=0, microsecond=0)
    h1 = h0 if t == h0 else h0 + timedelta(hours=1)
    pair = [(row["city"], h.isoformat()) for h in (h0, h1)]
    complete = all(k in hourly for k in pair)
    status = weather["weather_status"]
    if not complete:
        if status != "MISSING_BRACKETING_HOURLY_RECORDS" or any(
                number(weather[k], required=False) is not None for k in ("hrrr_t2m_K", "hrrr_vpd_kPa")):
            raise ValueError("Missing weather brackets silently filled")
        return None, None, None, None
    if status != "LINEAR_INTERPOLATION_OF_EXISTING_HOURLY_DOMAIN_MEANS":
        raise ValueError("Cached weather status does not match hourly archive")
    a = (t - h0).total_seconds() / 3600
    for cached, raw in (("hrrr_t2m_K", "t2m_k"), ("hrrr_vpd_kPa", "vpd_kpa")):
        calculated = (1-a) * number(hourly[pair[0]][raw]) + a * number(hourly[pair[1]][raw])
        if not math.isclose(calculated, number(weather[cached]), rel_tol=0, abs_tol=1e-9):
            raise ValueError("Cached acquisition-linked weather does not reconcile")
    return number(weather["hrrr_t2m_K"]), number(weather["hrrr_vpd_kPa"]), h0.isoformat(), h1.isoformat()


def check_output_scope(rows, original_ids):
    """Prevent accidental extra passes, new diagnostic effects or variant ambiguity."""
    keys = keyed(rows, ("city", "orbit", "source_run_id", "variant"))
    original = [r for r in rows if r["variant"] == "original"]
    actual = {(r["city"], str(r["orbit"]), r["source_run_id"], r["source_model_variant"]) for r in original}
    if actual != original_ids or len(original) != 16 or len(rows) != 64:
        raise ValueError("Output is not the frozen sixteen-pass/four-interval design")
    for row in rows:
        if timestamp(row["acquisition_utc"]).year != 2023 or row["source_model_variant"] != "paired_primary":
            raise ValueError("Output contains outside-scope model/year")
        size = row["resampling_group_km"]
        expected = "original" if size == 1 else f"spatial_uncertainty_{size}km"
        if size not in SIZES or row["variant"] != expected:
            raise ValueError("Spatial sensitivity label mismatch")
        if any(row[k] is not None for k in SEALED_FIELDS) or row["paired_effect_status"] != "SEALED_NOT_RELEASED":
            raise ValueError("Unreleased paired effect appeared in output")
    for r in original:
        for size in SIZES:
            variant = "original" if size == 1 else f"spatial_uncertainty_{size}km"
            s = keys[(r["city"], str(r["orbit"]), r["source_run_id"], variant)]
            for field in ("cooling_K_per_10pp", "n_cells", "footprint_area_km2", "apparent_solar_hour"):
                if s[field] != r[field]:
                    raise ValueError("Uncertainty sensitivity changed estimate/support")


class FrozenReader:
    """Only read named, hashed public sources. Sealed frame paths stay references."""
    def __init__(self, root, freeze):
        self.root = Path(root)
        self.inputs = {r["path"]: r["sha256"] for r in freeze["inputs"]}
        if (self.root / "data").resolve() != Path(freeze["data_link_target"]):
            raise ValueError("Data-link target changed after execution freeze")
        self.accessed = []

    def read(self, path, kind):
        if path not in self.inputs or "sealed_coefficients" in Path(path).parts or Path(path).suffix in (".npz", ".parquet"):
            raise ValueError("Input is outside public assembly allowlist")
        p = self.root / path
        if sha256(p) != self.inputs[path]:
            raise ValueError(f"Frozen source changed: {path}")
        self.accessed.append(path)
        with p.open() as handle:
            if kind == "csv":
                return list(csv.DictReader(handle))
            if kind == "json":
                return json.load(handle)
        raise ValueError("Unsupported public input type")
