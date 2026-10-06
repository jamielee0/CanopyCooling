"""Assemble the Step 2 review packet exclusively from frozen released sources.

Usage: PYTHONPATH=src python -m v6_2_advance.run_results_packet --freeze
       PYTHONPATH=src python -m v6_2_advance.run_results_packet --assemble
The final CSV is authored by the adjacent artifact-tool builder after assembly.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .results_packet import (
    FrozenReader, MODEL_VARIANTS, SEALED_FIELDS, SIZES, check_output_scope, collection_label,
    footprint_area_km2, integer, keyed, number, reconcile_estimate, sha256,
    solar_times, support_quantiles, timestamp, validate_weather,
)

ROOT = Path(__file__).resolve().parents[2]
EXEC = ROOT / "docs/v2/v6_2/execution/results_packet_20261004"
OUT = ROOT / "deliverables/Results_Review_2023_v6_2_20261004"
RELEASED = "outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv"
SUPPORT = "docs/v2/v6_2/execution/nonlinear_association_20260930/numeric_support_freeze.json"
WEATHER = "deliverables/Methodology_and_Expansion_v6_2_20260921/descriptive_vpd_temperature.csv"
HOURLY = "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/hrrr_hourly_domain_summary.csv"
REFERENCE = "outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json"
SCOPE1 = "docs/v2/v6_2/execution/results_review_20261004/scope.json"
RUN_MANIFESTS = {
    "pooled_pilot_20260919_phoenix": "docs/v2/v6_2/execution/phoenix_execution_manifest.json",
    "pooled_pilot_20260919_atlanta": "docs/v2/v6_2/execution/atlanta_execution_manifest.json",
    "pooled_extension_20260921_phoenix": "docs/v2/v6_2/execution/advance_20260921/phoenix_execution_manifest.json",
}
REPOSITORY_ARTIFACTS = (
    "src/v6_2_advance/results_packet.py", "src/v6_2_advance/run_results_packet.py",
    "tests/v6_2_advance/test_results_packet.py",
    "docs/v2/v6_2/execution/results_packet_20261004/build_results_csv.mjs",
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def audit_path(run, orbit):
    prefix = f"outputs/v6_2/scientific/{run}/"
    return prefix + (f"{orbit}_native_ownership_audit.csv" if "extension" in run else "native_ownership_audit.csv")


def freeze_inputs():
    """Freeze public input identities, scope and clock before assembling results."""
    from shapely.geometry import shape
    freeze_path = EXEC / "execution_freeze.json"
    if freeze_path.exists():
        raise ValueError("Existing freeze is immutable; use --assemble")
    scope = json.loads((ROOT / SCOPE1).read_text())
    identities = scope["main_pilot"]["pass_identities"]
    sources = {RELEASED, SUPPORT, WEATHER, HOURLY, REFERENCE, SCOPE1,
               "outputs/v6_2/scientific/exploratory_review_20260921/gradient_disclosure.json",
               "docs/v2/v6_2/execution/limited_gradient_disclosure_20260919.json"}
    cities = {}
    for run, path in RUN_MANIFESTS.items():
        sources.add(path)
        prefix = f"outputs/v6_2/scientific/{run}/"
        sources.add(prefix + "precision.csv")
        if "extension" not in run:
            sources.add(prefix + "spatial_stress_precision.csv")
            m = json.loads((ROOT / path).read_text())
            c = shape(m["domain"]).centroid
            cities[m["city"]] = {
                "longitude_deg": c.x, "latitude_deg": c.y,
                "longitude_rule": "centroid_of_frozen_WGS84_domain_geometry",
                "longitude_source": path,
                "analysis_crs": f"EPSG:{m['city_epsg']}",
                "civil_timezone": "America/Phoenix" if m["city"] == "phoenix" else "America/New_York",
            }
    sources.update(audit_path(r["run_id"], r["orbit"]) for r in identities)
    write_json(freeze_path, {
        "created_utc": datetime.now(timezone.utc).isoformat(), "record_date_local": "2026-10-04",
        "authority": {"request": "ok, do the next part", "authorized_step": 2,
                      "plan": "docs/v2/v6_2/results_review_and_targeted_analysis_plan_20260930.md"},
        "status": "FROZEN_BEFORE_ASSEMBLY", "data_link_target": str((ROOT / "data").resolve(strict=True)),
        "original_identities": identities, "cities": cities,
        "design": {"original_rows": 16, "uncertainty_sensitivity_rows": 48,
                   "spatial_group_sizes_km": list(SIZES), "new_models": 0, "new_time_comparisons": 0,
                   "new_thermal_reads": 0, "sealed_model_access": False, "new_effect_release": False,
                   "rainfall_retrieval": False, "VPD": "descriptive only",
                   "flux_effect_fields": "blank; SEALED_NOT_RELEASED",
                   "clock": "fractional UTC hour + east-positive longitude/15 + harmonic equation of time/60; modulo 24",
                   "equation_of_time": "repository audit harmonic formula, gamma with 365/366-day year; subsecond precision retained",
                   "area": "sum of unique selected whole 70m native footprints; not city-clipped area or domain coverage fraction",
                   "plots": "all original passes, separate city figures, 1km and 8km percentile panels; no fitted curve"},
        "inputs": [{"path": p, "bytes": (ROOT/p).stat().st_size, "sha256": sha256(ROOT/p)} for p in sorted(sources)],
        "code_at_freeze": [{"path": p, "sha256": sha256(ROOT/p)} for p in REPOSITORY_ARTIFACTS],
    })
    print(json.dumps({"freeze": str(freeze_path), "public_sources": len(sources), "cities": cities}, indent=2))


def field_specs():
    """Each CSV variable has an explicit definition, type, unit and missing rule."""
    fields = []
    def add(name, dtype, unit, definition, missing="never missing"):
        fields.append(dict(name=name, type=dtype, unit=unit, definition=definition, missing=missing))
    for name, desc in {
        "city": "Frozen city identifier", "orbit": "ECOSTRESS acquisition orbit, retained as identifier text",
        "variant": "original (1km intervals) or spatial_uncertainty_2/4/8km; same point model and cells",
        "source_run_id": "Original scientific run identity",
        "source_model_variant": "paired_primary original point model",
        "source_resampling_variant": "paired_primary or spatial_2/4/8km interval source",
        "acquisition_utc": "Exact acquisition instant as timezone-aware ISO8601 UTC",
        "civil_datetime": "Acquisition in city's IANA civil timezone, explicit UTC offset",
        "civil_timezone": "IANA timezone identifier", "local_date": "Civil acquisition date, YYYY-MM-DD",
        "collection": "ECOSTRESS collection identifier as text; retain leading zeros",
        "source_collection_label": "Unmodified collection label in released CSV; previous numeric export wrote 2 for 002",
        "sample_status": "2023 observational pilot; exploratory after prior release",
        "analysis_crs": "Original projected city coordinate reference system",
    }.items(): add(name, "string", "identifier or ISO8601", desc)
    add("month", "integer", "calendar month", "Month of local civil acquisition date")
    for name, desc in {
        "solar_longitude_deg": "East-positive frozen geographic-domain centroid longitude",
        "equation_of_time_min": "Harmonic equation-of-time correction, documented in execution freeze",
        "mean_solar_hour": "Computed UTC fractional hour + longitude/15, modulo 24",
        "apparent_solar_hour": "Computed mean solar hour + equation-of-time/60, modulo 24; plotted x",
        "source_plot_solar_hour": "Unmodified solar_hour in released pass table",
        "apparent_minus_source_solar_seconds": "Signed wrapped clock difference in seconds relative to released plot time",
    }.items(): add(name, "number", "degree" if name.endswith("deg") else "minute" if name.endswith("min") else "second" if name.endswith("seconds") else "hour", desc)
    for name, src in (("source_mean_solar_hour", "local_mean_solar_hour"),
                      ("source_apparent_solar_hour", "apparent_local_solar_hour"),
                      ("source_inherited_solar_hour", "local_solar_hour_inherited_metadata")):
        add(name, "number", "hour", f"Unmodified {src} from released pass table", "blank where that inherited field was absent; use computed apparent_solar_hour")
    add("signed_slope_T_K_per_canopy_fraction", "number", "K / unit canopy fraction", "10 × released signed temperature change per +10pp")
    add("signed_change_T_K_per_10pp", "number", "K / +10pp canopy", "Released conditional linear temperature change, 0.10 × canopy slope")
    for name, desc in {
        "cooling_K_per_10pp": "Negative signed temperature change; positive means lower mixed-pixel LST",
        "spatial_SE_K_per_10pp": "Sample SD (ddof=1) of existing whole-group bootstrap temperature changes",
        "cooling_q025_K_per_10pp": "Existing 2.5th percentile of sign-reversed bootstrap temperature changes",
        "cooling_q975_K_per_10pp": "Existing 97.5th percentile of sign-reversed bootstrap temperature changes",
        "interval_width_K_per_10pp": "97.5th minus 2.5th percentile, checked against independent public precision",
        "cluster_sandwich_SE_K_per_10pp": "Previously published cluster-sandwich SE for the same spatial grouping",
    }.items(): add(name, "number", "K / +10pp canopy", desc)
    add("interval_method", "string", "method", "Existing 95% percentile bootstrap; whole physical spatial groups, original 1km block intercepts")
    add("resampling_group_km", "integer", "km", "Side length of resampling group; does not change the fitted mean model")
    for name in ("resampling_groups", "bootstrap_requested", "bootstrap_estimable", "bootstrap_failed", "bootstrap_seed"):
        add(name, "integer", "count" if name != "bootstrap_seed" else "seed", "Existing precision record: " + name)
    for name in SEALED_FIELDS:
        add(name, "number", "W/m² / +10pp canopy" if "W_m2" in name else "K / +10pp canopy",
            "Reserved paired diagnostic effect field; no coefficient read or conversion in this step", "always blank: SEALED_NOT_RELEASED")
    add("paired_effect_status", "string", "status", "SEALED_NOT_RELEASED; prior LST reuse does not authorize flux or equivalent display")
    add("flux_spatial_SE_W_m2_per_10pp", "number", "W/m² / +10pp canopy", "Permitted existing public flux precision for matched spatial grouping, no effect")
    add("flux_interval_width_W_m2_per_10pp", "number", "W/m² / +10pp canopy", "Permitted existing public flux percentile width; endpoints withheld")
    add("reference_temperature_K", "number", "K", "Existing September19 fixed reference; metadata only, no new transformation")
    add("reference_emissivity", "number", "fraction", "Existing September19 fixed reference emissivity")
    add("reference_status", "string", "status", "Historical original-ten-pass reference metadata; applicability to six additions not established here")
    add("reference_source", "string", "relative repository path", "Exact numeric reference manifest, hashed in freeze")
    for name, desc in {
        "n_cells": "Unique paired complete native cells in original fit (cell-pass observations)",
        "n_blocks": "Original occupied 1km intercept blocks",
        "contributing_blocks": "Blocks contributing within-block canopy information",
        "design_rank": "Rank of original within-block slope/context design",
        "residual_degrees_of_freedom": "Original fit residual degrees of freedom",
    }.items(): add(name, "integer", "count", desc)
    add("footprint_area_km2", "number", "km²", "Sum of unique retained whole native-cell footprints: n × 4900 m² / 1e6; reconcile canonical tile audit; not city-clipped area")
    add("footprint_area_status", "string", "status", "VERIFIED_CANONICAL_WHOLE_CELLS; selected cell centres fall in domain; edge cells are not clipped")
    for name, desc, unit in (
        ("within_block_canopy_Sxx", "Sum of squared block-demeaned canopy fractions", "fraction²"),
        ("within_block_canopy_variance", "Published within_block_variance; Sxx divided by n_cells", "fraction²"),
        ("residualized_canopy_Sxx", "Canopy information remaining after block intercepts and context controls", "fraction²"),
        ("maximum_block_information_share", "Largest block share of residualized canopy information", "fraction"),
        ("top_five_block_information_share", "Sum of five largest residualized information shares", "fraction"),
        ("effective_information_blocks", "Inverse sum of squared residualized block information shares", "effective blocks"),
        ("maximum_slope_design_leverage", "Published maximum single-cell canopy-slope leverage", "fraction"),
    ): add(name, "number", unit, desc)
    add("removed_context_terms", "string", "JSON array", "Context terms removed from the original design; no redesign at assembly")
    for q in ("0", "0.01", "0.05", "0.1", "0.25", "0.35", "0.5", "0.65", "0.75", "0.9", "0.95", "0.99", "1"):
        add("canopy_q" + q.replace(".", "p"), "number", "fraction", f"Cell-weighted canopy fraction quantile at probability {q}, reused from predictor-only support snapshot; no cutoff")
    add("view_zenith_p95_deg", "number", "degree", "Inherited pass p95 sensor view zenith, not mean or solar zenith")
    for name, desc in {
        "geometry_coverage_status": "NOT_QUANTIFIED_IN_REUSED_SOURCES; p95 alone does not establish complete cell-level geometry",
        "view_azimuth_status": "UNRESOLVED_FROZEN_PILOT_EXCEPTION; do not claim completed azimuth recovery",
        "geometry_exception_status": "Frozen 25-degree pilot precision exception retained as inherited metadata",
        "weather_status": "Cached linked HRRR interpolation status or missing bracketing hourly records",
    }.items(): add(name, "string", "status", desc)
    add("air_temperature_K", "number", "K", "Cached HRRR 2m domain-mean air temperature interpolated at exact acquisition, independently reconciled", "blank: MISSING_BRACKETING_HOURLY_RECORDS")
    add("VPD_kPa", "number", "kPa", "Cached HRRR domain-mean VPD interpolated at exact acquisition; descriptive only", "blank: MISSING_BRACKETING_HOURLY_RECORDS")
    add("source_inherited_VPD_kPa", "number", "kPa", "Unmodified inherited VPD metadata from released table, kept distinct from linked HRRR fields", "blank: inherited metadata absent")
    for name in ("weather_bracket_start_utc", "weather_bracket_end_utc"):
        add(name, "string", "ISO8601 UTC", "Exact existing hourly bracket used for HRRR interpolation", "blank: MISSING_BRACKETING_HOURLY_RECORDS")
    for days in (1, 3, 7):
        add(f"rainfall_prior_{days}d_mm", "number", "mm", f"Reserved antecedent rainfall total over {days} days before acquisition", "always blank: NOT_ACQUIRED")
    add("rainfall_status", "string", "status", "NOT_ACQUIRED; no cached acquisition-linked totals located or retrieved in this step")
    for name, desc in {
        "source_precision": "Public source of group/draw accounting and paired precision",
        "source_ownership_audit": "Canonical tile ownership/count/area audit used for this pass",
        "source_predictor_snapshot": "Predictor-only support freeze reused without opening cached thermal frame",
        "native_frame_sha256_recorded": "Historical input-frame checksum from predictor freeze, not a new checksum/read of sealed frame",
        "source_weather": "Cached exact-acquisition weather table; raw hourly source in execution manifest",
    }.items(): add(name, "string", "path or SHA256", desc)
    return fields


def assemble():
    freeze = json.loads((EXEC / "execution_freeze.json").read_text())
    reader = FrozenReader(ROOT, freeze)
    released = reader.read(RELEASED, "csv")
    original_ids = {(r["city"], str(r["orbit"]), r["run_id"], r["variant"]) for r in freeze["original_identities"]}
    released_keys = keyed(released, ("city", "orbit", "run_id", "variant"))
    if set(released_keys) != original_ids:
        raise ValueError("Released pass set differs from frozen 2023 sample")
    support = reader.read(SUPPORT, "json")
    if support["outcome_columns_read"] is not False:
        raise ValueError("Expected predictor-only support snapshot")
    support_keys = keyed(support["passes"], ("city", "orbit", "run_id"))
    weather_keys = keyed(reader.read(WEATHER, "csv"), ("city", "orbit"))
    hourly = {}
    duplicate_hourly = 0
    for r in reader.read(HOURLY, "csv"):
        key = (r["city"], timestamp(r["timestamp_utc"]).isoformat())
        if key in hourly:
            if any(r[k] != hourly[key][k] for k in ("t2m_k", "vpd_kpa", "source", "domain_cell_rule")):
                raise ValueError("Conflicting duplicate hourly weather records")
            duplicate_hourly += 1
        else: hourly[key] = r
    reference = reader.read(REFERENCE, "json")
    precision_keys = {}
    for run in RUN_MANIFESTS:
        prefix = f"outputs/v6_2/scientific/{run}/"
        sources = [prefix + "precision.csv"]
        if "extension" not in run: sources.append(prefix + "spatial_stress_precision.csv")
        for path in sources:
            for r in reader.read(path, "csv"):
                if r["variant"] in MODEL_VARIANTS.values():
                    city, orbit = r["pass_id"].split(":")
                    key = (city, orbit, run, r["variant"])
                    if key in precision_keys: raise ValueError("Duplicate public precision identity")
                    precision_keys[key] = (r, path)
    manifests = {run: reader.read(p, "json") for run, p in RUN_MANIFESTS.items()}
    audit_cache = {}
    rows = []
    for size in SIZES:
        for r in sorted(released, key=lambda x: (x["city"], x["acquisition_utc"])):
            city, orbit, run = r["city"], r["orbit"], r["run_id"]
            t = timestamp(r["acquisition_utc"])
            metadata = manifests[run]["pass_metadata"][orbit]
            collection = collection_label(r["collection"], metadata["collection"])
            if timestamp(metadata["acquisition_utc"]) != t:
                raise ValueError("Acquisition/product differs from original execution manifest")
            c = freeze["cities"][city]
            civil = t.astimezone(ZoneInfo(c["civil_timezone"]))
            mean, apparent, eot = solar_times(t, c["longitude_deg"])
            qsource = support_keys[(city, orbit, run)]
            quantiles = support_quantiles(qsource, r)
            p, precision_source = precision_keys[(city, orbit, run, MODEL_VARIANTS[size])]
            gradient, cooling, se, low, high = reconcile_estimate(r, p, size)
            if size == 8 and integer(p["resampling_groups"]) != qsource["n_8km_groups"]:
                raise ValueError("Predictor snapshot spatial groups do not reconcile")
            apath = audit_path(run, orbit)
            if apath not in audit_cache: audit_cache[apath] = reader.read(apath, "csv")
            audit = audit_cache[apath]
            if "extension" not in run: audit = [a for a in audit if a["orbit"] == orbit]
            if any(a["city"] != city for a in audit): raise ValueError("Ownership audit city mismatch")
            area = footprint_area_km2(audit, integer(r["n_cells"]))
            w = weather_keys[(city, orbit)]
            air, vpd, h0, h1 = validate_weather(r, w, hourly)
            inherited_vpd = number(r["vpd_kpa_inherited_metadata"], required=False)
            if inherited_vpd != number(w["vpd_kpa_inherited_metadata"], required=False):
                raise ValueError("Inherited VPD metadata disagreement")
            row = {
                "city": city, "orbit": orbit,
                "variant": "original" if size == 1 else f"spatial_uncertainty_{size}km",
                "source_run_id": run, "source_model_variant": r["variant"], "source_resampling_variant": MODEL_VARIANTS[size],
                "acquisition_utc": r["acquisition_utc"], "civil_datetime": civil.isoformat(),
                "civil_timezone": c["civil_timezone"], "local_date": civil.date().isoformat(),
                "collection": collection, "source_collection_label": r["collection"], "sample_status": "2023 observational pilot; exploratory after prior release",
                "analysis_crs": c["analysis_crs"], "month": civil.month,
                "solar_longitude_deg": c["longitude_deg"], "equation_of_time_min": eot,
                "mean_solar_hour": mean, "apparent_solar_hour": apparent,
                "source_plot_solar_hour": number(r["solar_hour"]),
                "apparent_minus_source_solar_seconds": ((apparent - number(r["solar_hour"]) + 12) % 24 - 12) * 3600,
                "source_mean_solar_hour": number(r["local_mean_solar_hour"], required=False),
                "source_apparent_solar_hour": number(r["apparent_local_solar_hour"], required=False),
                "source_inherited_solar_hour": number(r["local_solar_hour_inherited_metadata"], required=False),
                "signed_slope_T_K_per_canopy_fraction": gradient * 10,
                "signed_change_T_K_per_10pp": gradient, "cooling_K_per_10pp": cooling,
                "spatial_SE_K_per_10pp": se, "cooling_q025_K_per_10pp": low, "cooling_q975_K_per_10pp": high,
                "interval_width_K_per_10pp": high - low,
                "cluster_sandwich_SE_K_per_10pp": number(p["LST_K_cluster_sandwich_SE_per_10pp"]),
                "interval_method": "95% percentile bootstrap; whole spatial groups; original 1km block intercepts",
                "resampling_group_km": size, "resampling_groups": integer(p["resampling_groups"]),
                "bootstrap_requested": integer(p["bootstrap_requested"]), "bootstrap_estimable": integer(p["bootstrap_estimable"]),
                "bootstrap_failed": integer(p["bootstrap_failed"]), "bootstrap_seed": integer(p["seed"]),
                **{k: None for k in SEALED_FIELDS}, "paired_effect_status": "SEALED_NOT_RELEASED",
                "flux_spatial_SE_W_m2_per_10pp": number(p["M_W_m2_SE_per_10pp"]),
                "flux_interval_width_W_m2_per_10pp": number(p["M_W_m2_bootstrap_width_95_per_10pp"]),
                "reference_temperature_K": reference["reference_K"], "reference_emissivity": reference["reference_emissivity"],
                "reference_status": "HISTORICAL_TEN_PASS_REFERENCE; six-added-pass applicability not established here",
                "reference_source": REFERENCE,
                "n_cells": integer(r["n_cells"]), "n_blocks": integer(r["n_blocks"]),
                "contributing_blocks": integer(r["contributing_blocks"]), "design_rank": integer(r["design_rank"]),
                "residual_degrees_of_freedom": integer(r["residual_degrees_of_freedom"]),
                "footprint_area_km2": area, "footprint_area_status": "VERIFIED_CANONICAL_WHOLE_CELLS; domain edges not clipped",
                "within_block_canopy_Sxx": number(r["within_block_Sxx"]),
                "within_block_canopy_variance": number(r["within_block_variance"]),
                "residualized_canopy_Sxx": number(r["residualized_canopy_Sxx"]),
                "maximum_block_information_share": number(r["maximum_block_information_share"]),
                "top_five_block_information_share": number(r["top_five_block_information_share"]),
                "effective_information_blocks": number(r["effective_information_blocks"]),
                "maximum_slope_design_leverage": number(p["maximum_slope_design_leverage"]),
                "removed_context_terms": r["removed_context_terms"],
                **{"canopy_q"+k.replace(".", "p"): v for k, v in quantiles.items()},
                "view_zenith_p95_deg": number(r["view_zenith_p95_deg"]),
                "geometry_coverage_status": "NOT_QUANTIFIED_IN_REUSED_SOURCES",
                "view_azimuth_status": "UNRESOLVED_FROZEN_PILOT_EXCEPTION",
                "geometry_exception_status": "FROZEN_25_DEGREE_PRECISION_EXCEPTION" if str(r["frozen_25_degree_precision_exception"]).lower() == "true" else "NOT_RECORDED",
                "weather_status": w["weather_status"], "air_temperature_K": air, "VPD_kPa": vpd,
                "source_inherited_VPD_kPa": inherited_vpd, "weather_bracket_start_utc": h0, "weather_bracket_end_utc": h1,
                **{f"rainfall_prior_{d}d_mm": None for d in (1, 3, 7)}, "rainfall_status": "NOT_ACQUIRED",
                "source_precision": precision_source, "source_ownership_audit": apath,
                "source_predictor_snapshot": SUPPORT, "native_frame_sha256_recorded": qsource["sha256"], "source_weather": WEATHER,
            }
            rows.append(row)
    check_output_scope(rows, original_ids)
    fields = field_specs()
    names = [f["name"] for f in fields]
    if any(set(row) != set(names) for row in rows): raise ValueError("Undocumented/missing CSV field")
    write_json(EXEC / "results_matrix.json", {"fields": fields, "rows": [[r[k] for k in names] for r in rows]})
    write_json(OUT / "data_dictionary.json", {"missing_encoding": "empty CSV field, never zero; consult field/status definitions",
                                           "record_key": ["city", "orbit", "source_run_id", "variant"], "fields": fields})
    dictionary = ["# Results table dictionary", "", "One row is one city-pass and spatial uncertainty variant. Exactly 16 `original` rows precede 48 uncertainty sensitivities. Sensitivity rows reuse the same estimate and cells; they are not additional observations. Canopy fraction ranges from 0 to 1; +10pp means +0.10. Positive cooling is minus the signed temperature change. Units of temperature differences are K, numerically equal to °C differences.", "", "Blank fields are missing or withheld, never zero. Machine-readable definitions are in `data_dictionary.json`. The execution freeze documents clock, area, input identities and SHA256 checksums. No new model or flux conversion was computed.", "", "| Variable | Type / unit | Definition | Missing-value rule |", "| --- | --- | --- | --- |"]
    dictionary += [f"| `{f['name']}` | {f['type']} / {f['unit']} | {f['definition']} | {f['missing']} |" for f in fields]
    (OUT / "data_dictionary.md").write_text("\n".join(dictionary) + "\n")
    originals = [r for r in rows if r["variant"] == "original"]
    missing = {"created_utc": datetime.now(timezone.utc).isoformat(), "scope": "16 original acquisitions; sensitivities repeat the same gaps", "fields": []}
    for field, status, condition in (
        ("air_temperature_K,VPD_kPa", "MISSING_BRACKETING_HOURLY_RECORDS", lambda r: r["air_temperature_K"] is None),
        ("rainfall_prior_1d_mm,rainfall_prior_3d_mm,rainfall_prior_7d_mm", "NOT_ACQUIRED", lambda r: True),
        ("cell_level_geometry_coverage", "NOT_QUANTIFIED_IN_REUSED_SOURCES", lambda r: True),
        ("view_azimuth_completeness", "UNRESOLVED_FROZEN_PILOT_EXCEPTION", lambda r: True),
        ("flux_and_temperature_equivalent_effects", "SEALED_NOT_RELEASED", lambda r: True),
    ):
        affected = [dict(city=r["city"], orbit=r["orbit"], local_date=r["local_date"]) for r in originals if condition(r)]
        missing["fields"].append(dict(field=field, status=status, affected_count=len(affected), acquisitions=affected))
    write_json(OUT / "missing_inputs.json", missing)
    summary = {}
    for city in ("phoenix", "atlanta"):
        q = [r for r in originals if r["city"] == city]
        q8 = [r for r in rows if r["city"] == city and r["resampling_group_km"] == 8]
        def span(q, field): return [min(r[field] for r in q), max(r[field] for r in q)]
        summary[city] = {"original_passes": len(q), "cooling_K_per_10pp_range": span(q, "cooling_K_per_10pp"),
                         "SE_1km_range": span(q, "spatial_SE_K_per_10pp"), "SE_8km_range": span(q8, "spatial_SE_K_per_10pp"),
                         "native_cells_range": span(q, "n_cells"), "footprint_area_km2_range": span(q, "footprint_area_km2"),
                         "canopy_median_range": span(q, "canopy_q0p5"), "complete_linked_weather": sum(r["air_temperature_K"] is not None for r in q),
                         "apparent_solar_hour_range": span(q, "apparent_solar_hour"),
                         "month_counts": dict(sorted(Counter(r["month"] for r in q).items())),
                         "intervals_8km_above_zero": sum(r["cooling_q025_K_per_10pp"] > 0 for r in q8)}
    write_json(OUT / "descriptive_summary.json", summary)
    write_json(EXEC / "assembly_verification.json", {
        "status": "PASSED_ASSEMBLY; final CSV roundtrip and visual QA pending",
        "row_counts": {"original": 16, "sensitivity": 48, "all": 64}, "column_count": len(fields),
        "checks_passed": ["frozen source hashes", "16 exact city/orbit/run/model identities", "2023 only",
                          "unique composite keys", "acquisition/product manifest joins", "signed units",
                          "all four SE/percentile widths versus independent precision", "draw accounting",
                          "all 16 canonical ownership counts and areas", "predictor support counts and quantiles",
                          "8km group counts", "linked weather and missing bracket cross-check",
                          "complete dictionary coverage", "sealed diagnostic effect fields blank"],
        "max_absolute_clock_change_seconds": max(abs(r["apparent_minus_source_solar_seconds"]) for r in originals),
        "duplicate_identical_hourly_weather_rows": duplicate_hourly,
        "public_sources_read": sorted(set(reader.accessed)), "sealed_files_opened": [],
        "new_models_fitted": 0, "new_empirical_time_comparisons": 0,
        "runtime": "urbanv2 Python 3.11 (existing matplotlib/shapely); bundled Node artifact-tool for final CSV",
        "code_at_execution": [{"path": p, "sha256": sha256(ROOT/p)} for p in REPOSITORY_ARTIFACTS],
    })
    plot_cities(rows)
    print(json.dumps({"rows": len(rows), "columns": len(fields), "summary": summary}, indent=2))


def plot_cities(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    colors = {6: "#2878b5", 7: "#d77d00", 8: "#9b4f96", 9: "#25856d"}
    months = {6: "June", 7: "July", 8: "August", 9: "September"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False})
    point_manifest = []
    offsets = {"27963": (16, -25), "28909": (-25, 17), "29545": (-46, -25),
               "28024": (10, 17), "28970": (-65, -18), "29606": (10, -9),
               "28085": (7, 13), "28192": (8, -15), "28828": (9, 10),
               "27835": (10, 9), "28145": (-63, 10)}
    for city in ("phoenix", "atlanta"):
        q = [r for r in rows if r["city"] == city and r["variant"] == "original"]
        city_rows = [r for r in rows if r["city"] == city and r["resampling_group_km"] in (1, 8)]
        ymax = max(r["cooling_q975_K_per_10pp"] for r in city_rows)
        fig, axes = plt.subplots(2, 1, figsize=(10.4, 8.3), sharex=True, sharey=True)
        for ax, size in zip(axes, (1, 8)):
            panel = [r for r in city_rows if r["resampling_group_km"] == size]
            for r in panel:
                x, y = r["apparent_solar_hour"], r["cooling_K_per_10pp"]
                color = colors[r["month"]]
                marker = "s" if "extension" in r["source_run_id"] else "o"
                ax.vlines(x, r["cooling_q025_K_per_10pp"], r["cooling_q975_K_per_10pp"], color=color, linewidth=1.6)
                ax.scatter(x, y, s=67, c=color, marker=marker, edgecolor="white", linewidth=.6, zorder=3)
                ax.annotate(r["local_date"][5:], (x, y), xytext=offsets.get(r["orbit"], (8, 8)),
                            textcoords="offset points", fontsize=9, color="#344054",
                            arrowprops={"arrowstyle": "-", "color": "#667085", "lw": .65} if r["orbit"] in ("27963", "29545") else None)
                point_manifest.append({k: r[k] for k in ("city", "orbit", "source_run_id", "source_model_variant", "variant",
                    "acquisition_utc", "local_date", "apparent_solar_hour", "cooling_K_per_10pp",
                    "cooling_q025_K_per_10pp", "cooling_q975_K_per_10pp", "resampling_group_km")})
            ax.axhline(0, color="#667085", linewidth=.8)
            ax.grid(axis="y", alpha=.18)
            ax.set_title(f"{size} km spatial groups · existing 95% percentile intervals", loc="left", fontsize=11)
            ax.set_ylabel("Cooling (K per +10 pp canopy)")
            ax.set_xlim(9.5, 18.3)
            ax.set_ylim(-.04 * ymax, 1.12 * ymax)
            ax.set_xticks(range(10, 19))
        axes[-1].set_xlabel("Apparent local solar time (hours)")
        fig.suptitle(f"{city.title()} · {len(q)} acquisitions in 2023", x=.105, ha="left", fontsize=19, weight="bold")
        fig.text(.105, .914, "Canopy-associated mixed-pixel surface cooling · positive values mean lower LST", fontsize=11, color="#475467")
        legend = [Line2D([0], [0], color=colors[m], marker="o", ls="", label=months[m]) for m in sorted({r["month"] for r in q})]
        if city == "phoenix":
            legend += [Line2D([0], [0], color="#667085", marker="s", ls="", label="Added 21 September 2026")]
        fig.legend(handles=legend, loc="lower center", bbox_to_anchor=(.52, .055), ncol=len(legend), frameon=False, fontsize=10)
        fig.text(.105, .033, "All original passes shown. Same point estimates and cells in both panels. No time model fitted.", fontsize=10, color="#475467")
        fig.text(.105, .012, "Intervals describe within-pass spatial uncertainty; they do not quantify a temporal trend.", fontsize=10, color="#475467")
        fig.subplots_adjust(left=.105, right=.974, top=.86, bottom=.16, hspace=.23)
        fig.savefig(OUT / f"{city}_cooling_vs_apparent_solar_time.png", dpi=180)
        fig.savefig(OUT / f"{city}_cooling_vs_apparent_solar_time.pdf")
        plt.close(fig)
    write_json(OUT / "plot_points.json", {"plots": "1km and 8km panels; all 16 originals repeated once per panel", "points": point_manifest})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--assemble", action="store_true")
    args = parser.parse_args()
    freeze_inputs() if args.freeze else assemble()
