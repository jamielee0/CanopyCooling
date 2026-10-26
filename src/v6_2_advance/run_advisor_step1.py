"""Section 7 Step 1: exact scene QA and nonthermal HRRR inputs for 23 passes.

No model, native thermal frame, or other-year cooling estimate is read.
The named historical run remains frozen; this runner writes to a new dated run.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import re

import eccodes as ec
import numpy as np
import pandas as pd
import requests
import shapely

from .advisor_step1_inputs import (
    OTHER_YEAR_ORBITS, check_holdout_blanks, exact_geo_flag, hash_file,
    interpolate_shortwave, read_other_year_metadata, scene_summary, sun_at,
)
from .run_step6_inputs import FIELDS, FIELD_SHORT_NAMES, FIELD_UNITS, domains
from .step6_inputs import brackets, grib_ranges, vpd_kpa

ROOT = Path(__file__).resolve().parents[2]
RUN = "advisor_step1_20261026"
EXEC = ROOT / "docs/v2/v6_2/execution" / RUN
OUT = ROOT / "outputs/v6_2/scientific" / RUN
PACKET = ROOT / "deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026"
OLD = ROOT / "outputs/v6_2/scientific/step6_inputs_20261005"
PASS_TABLE = "review/current/01_existing_results/pass_results_with_conditions.csv"
NEW_SELECTION = "docs/v2/v6_2/execution/rebalance_20260921/new7_selected_passes.csv"
NEW_SUPPORT = "deliverables/Sampling_Rebalance_v6_2_20260921/all18_pass_roles_and_precision.csv"
GEO_LEDGER = "data/processed/v2/task1/step2_enrichment/geolocation_resolution.csv"
GEO_OFFICIAL = "data/processed/v2/task1/step2_enrichment/official_scene_metadata.csv"
CLOCK_FREEZE = "docs/v2/v6_2/execution/results_packet_20261004/execution_freeze.json"
CODE = ["src/v6_2_advance/" + n for n in (
    "advisor_step1_inputs.py", "run_advisor_step1.py", "run_step6_inputs.py",
    "step6_inputs.py", "results_packet.py")]
CODE += ["tests/v6_2_advance/test_advisor_step1_inputs.py"]
PATTERN = re.compile(r"ECOv002_L2T_LSTE_(\d+)_(\d+)_([A-Z0-9]+)_(\d+T\d+)_(\d+)_(\d+)_LST.tif")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def rel(path):
    return str(Path(path).relative_to(ROOT))


def load_table():
    with (ROOT / PASS_TABLE).open() as f:
        reader = csv.DictReader(f)
        columns, rows = reader.fieldnames, list(reader)
    if len(rows) != 16 or any(r["acquisition_utc"][:4] != "2023" for r in rows):
        raise ValueError("The reviewed sixteen-pass source changed")
    if sum(r["city"] == "phoenix" for r in rows) != 11:
        raise ValueError("Unexpected city membership")
    for row in rows:
        row.update(sample_role="main_2023", effect_access_status="previously_released_2023",
                   source_run_id=row["run_id"], local_date=row["date"])
    seven = read_other_year_metadata(ROOT / NEW_SELECTION)
    if len(seven) != 7 or {int(r["orbit"]) for r in seven} != OTHER_YEAR_ORBITS:
        raise ValueError("Other-year selection changed")
    support_columns = ["orbit", "n_cells", "n_blocks", "contributing_blocks", "within_block_Sxx"]
    support = pd.read_csv(ROOT / NEW_SUPPORT, usecols=support_columns, dtype=str).fillna("")
    if support.orbit.duplicated().any():
        raise ValueError("Duplicate nonthermal support rows")
    support = support.set_index("orbit").to_dict("index")
    for meta in seven:
        row = {key: "" for key in columns}
        orbit = str(int(meta["orbit"]))
        row.update(support[orbit])
        row.update(city="phoenix", orbit=orbit, pass_id=f"phoenix:{orbit}", variant="original",
                   acquisition_utc=meta["acquisition_utc"], date=meta["local_date"],
                   local_date=meta["local_date"], month=meta["month"], collection="002",
                   run_id="pooled_rebalance_20260921_phoenix", source_run_id="pooled_rebalance_20260921_phoenix",
                   sample_role="other_year_prediction_inputs_only",
                   effect_access_status="NOT_OPENED_AWAITING_COMMITTED_STEP3_PREDICTIONS",
                   sample="other_year_extension", review_scope="Step1 nonthermal inputs only",
                   view_zenith_p95_deg=meta["l1b_view_zenith_abs_p95_deg"],
                   source_apparent_solar_hour=meta["solar_hour"])
        rows.append(row)
    if len({(r["city"], r["orbit"]) for r in rows}) != 23:
        raise ValueError("Duplicate pass identities")
    check_holdout_blanks(rows)
    return columns, sorted(rows, key=lambda r: (r["city"], r["acquisition_utc"]))


def collect_geo(rows):
    cache = {}
    for p in (ROOT / "data/raw/v2").rglob("*.dmrpp"):
        cache.setdefault(p.name, []).append(p)
    ledger = {(int(r["orbit"]), int(r["scene"])): r for r in csv.DictReader((ROOT / GEO_LEDGER).open())}
    official = list(csv.DictReader((ROOT / GEO_OFFICIAL).open()))
    observed_rules = {(r["geolocation_quality"], r["geolocation_usable"]) for r in official}
    if observed_rules != {("best", "True"), ("good", "True"), ("suspect", "False"), ("poor", "False")}:
        raise ValueError("Census usability rule needs clarification")
    inputs, result = set(), []
    for row in rows:
        city, orbit = row["city"], int(row["orbit"])
        base = ROOT / f"data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/pass_evidence/{city}"
        evidence = next((base / f"{name}.json" for name in (str(orbit), f"{orbit:05d}")
                         if (base / f"{name}.json").is_file()), None)
        if evidence is None:
            raise ValueError(f"Missing source scene binding for {city}:{orbit}")
        data = json.loads(evidence.read_text())
        bindings = data["binding"]["scene_bindings"]
        model_time = pd.Timestamp(row["acquisition_utc"])
        binding_time = pd.Timestamp(data["binding"]["acquisition_utc"])
        time_difference = (binding_time-model_time).total_seconds()
        scene_starts = {pd.to_datetime(re.search(r"_(\d{8}T\d{6})_", b["granule_id"])[1], utc=True)
                        for b in bindings}
        if model_time.floor("s") not in scene_starts or binding_time.floor("s") not in scene_starts:
            raise ValueError("Pass timestamps do not identify bound scenes")
        if time_difference:
            scope = json.loads((EXEC / "scope.json").read_text())
            if (not scope.get("approved_keep_model_table_times") or orbit not in (6281, 33623, 40111, 40376)
                    or not 51 < time_difference < 53 or brackets(model_time)[:2] != brackets(binding_time)[:2]):
                raise ValueError("Unapproved acquisition-time discrepancy")
        raw = (ROOT / "data/raw/ecostress_lst" if city == "phoenix" and row["acquisition_utc"][:4] == "2023"
               else ROOT / "data/raw/v2/pilot_v6_2_20260919/atlanta_lste" if city == "atlanta"
               else ROOT / "data/raw/v2/rebalance_v6_2_20260921/thermal")
        # List names only. Do not open or hash any thermal raster.
        source_names = [p.name for p in raw.glob("*_LST.tif")
                        if (m := PATTERN.fullmatch(p.name)) and int(m[1]) == orbit]
        scenes = {int(PATTERN.fullmatch(n)[2]) for n in source_names}
        if scenes != {int(b["scene"]) for b in bindings}:
            raise ValueError("Thermal filename scenes differ from archived geometry binding")
        inputs.add(rel(evidence))
        for binding in bindings:
            key = (orbit, int(binding["scene"]))
            old = ledger.get(key)
            if old is None:
                raise ValueError("Scene absent from the named census ledger")
            gid = binding["granule_id"]
            matches = [p for p in cache.get(gid + ".h5.dmrpp", [])
                       if hash_file(p) == binding["dmrpp_sha256"]]
            if not matches:
                raise ValueError(f"No checksum-matched cached GEO metadata: {gid}")
            source = sorted(matches)[0]
            raw_flag, flag = exact_geo_flag(source.read_bytes(), gid)
            inputs.add(rel(source))
            result.append(dict(city=city, orbit=orbit, scene=int(binding["scene"]),
                               scene_key=f"{orbit:05d}_{int(binding['scene']):03d}",
                               category=flag, source_raw_flag=raw_flag,
                               geo_granule_id=gid, geo_metadata_path=rel(source),
                               geo_metadata_sha256=binding["dmrpp_sha256"],
                               binding_path=rel(evidence),
                               model_table_acquisition_utc=model_time.isoformat(),
                               geo_binding_acquisition_utc=binding_time.isoformat(),
                               geo_binding_minus_model_time_seconds=time_difference,
                               scene_acquisition_utc=old["acquisition_utc"],
                               thermal_filenames=[n for n in source_names if int(PATTERN.fullmatch(n)[2]) == key[1]],
                               census_category=old["geolocation_quality"],
                               census_raw_flag=old["raw_geolocation_accuracy_qa"],
                               census_source_rule=old["geolocation_source_rule"],
                               census_warning=old["geolocation_warnings"],
                               census_usable=old["geolocation_quality"] in ("best", "good")))
    return result, inputs


def prepare():
    if (EXEC / "execution_freeze.json").exists():
        raise ValueError("Existing Step1 freeze must be preserved")
    scope = json.loads((EXEC / "scope.json").read_text())
    if str((ROOT / "data").resolve(strict=True)) != scope["data_link_target"]:
        raise ValueError("Data link changed")
    columns, rows = load_table()
    scenes, geo_inputs = collect_geo(rows)
    old_clock = json.loads((ROOT / CLOCK_FREEZE).read_text())["cities"]
    polygons = domains()
    coordinates = {c: {"latitude": float(p.centroid.y), "longitude": float(old_clock[c]["longitude_deg"])}
                   for c, p in polygons.items()}
    jobs = {}
    for row in rows:
        city = row["city"]
        sun = sun_at(row["acquisition_utc"], **coordinates[city])
        if row["sample_role"] == "main_2023" and abs(float(row["apparent_solar_hour"]) - sun["apparent_solar_hour"]) > 1e-10:
            raise ValueError("Existing solar time does not reproduce")
        for time in set(brackets(row["acquisition_utc"])[:2]):
            jobs.setdefault(time.isoformat(), set()).add(city)
    inputs = {PASS_TABLE, NEW_SELECTION, NEW_SUPPORT, GEO_LEDGER, GEO_OFFICIAL, CLOCK_FREEZE,
              "data/raw/v2/domains/census_urban_areas.geojson", "docs/v2/v6_2/execution/step6_inputs_20261005/execution_freeze.json", *geo_inputs}
    cfg = dict(record_date="2026-10-26", created_utc=datetime.now(timezone.utc).isoformat(),
               data_link_target=scope["data_link_target"], source_columns=columns, passes=rows,
               coordinates=coordinates, scene_records=scenes,
               weather_jobs=[dict(time=k, cities=sorted(v)) for k, v in sorted(jobs.items())],
               inputs={p: hash_file(ROOT / p) for p in sorted(inputs)},
               code_sha256={p: hash_file(ROOT / p) for p in CODE},
               settings={"product": "NOAA HRRR CONUS wrfsfcf00 analysis only, no substitute products",
                         "pass_time": "retain recorded model/selection-table acquisition times; four user-approved 52-second differences from older geometry bindings are explicitly retained",
                         "fields": FIELDS, "short_names": FIELD_SHORT_NAMES, "units": FIELD_UNITS,
                         "spatial": "equal-cell mean of grid centers covered by the same repaired Census urban polygons as Step6",
                         "radiation_timing": "interpolate sw/cos(zenith), then multiply by acquisition cosine; single usable ratio if the other cosine <0.1",
                         "solar": "inherited solar_times clock and solar_geometry harmonic declination at frozen city coordinates; UTC day of year; actual 365/366-day year",
                         "weather_timing": "linear interpolation of domain summaries for temperature, dewpoint, VPD and wind speed",
                         "census_usable_categories": ["best", "good"],
                         "other_year_effects": "all effect fields remain blank; no model or coefficient files read",
                         "fits": 0, "rainfall": "retain prior 2023 descriptors; no new other-year rainfall retrieval in Step1"})
    write(EXEC / "execution_freeze.json", cfg)
    print(json.dumps({"stage": "prepared", "passes": len(rows), "source_scenes": len(scenes), "hourly_jobs": len(jobs)}), flush=True)


def config():
    cfg = json.loads((EXEC / "execution_freeze.json").read_text())
    if str((ROOT / "data").resolve(strict=True)) != cfg["data_link_target"]:
        raise ValueError("Data link changed")
    for p, expected in {**cfg["inputs"], **cfg["code_sha256"]}.items():
        if hash_file(ROOT / p) != expected:
            raise ValueError("Frozen input or code changed: " + p)
    return cfg


def fetch(url, path, span=None):
    sidecar = path.with_suffix(path.suffix + ".json")
    if path.exists() and sidecar.exists():
        m = json.loads(sidecar.read_text())
        if m["url"] != url or m["sha256"] != hash_file(path) or m.get("byte_range") != (list(span) if span else None):
            raise ValueError("Download cache mismatch")
        return m
    # Preserve the metadata-only probe as a separate file before obtaining a
    # fully recorded transfer. Never infer a missing download provenance record.
    if path.exists():
        probe = path.with_suffix(path.suffix + ".preflight")
        if probe.exists():
            raise ValueError("Untracked cache collision")
        path.rename(probe)
    response = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"Range": f"bytes={span[0]}-{span[1]}"} if span else {}, timeout=(15, 60))
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2 or (response is not None and response.status_code == 404):
                raise
    if span:
        if response.status_code != 206 or len(response.content) != span[1]-span[0]+1:
            raise ValueError("Server ignored the requested field byte range")
        if not response.headers.get("Content-Range", "").startswith(f"bytes {span[0]}-{span[1]}/"):
            raise ValueError("Wrong HTTP content range")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    m = dict(url=url, byte_range=list(span) if span else None, status=response.status_code,
             bytes=len(response.content), sha256=hash_file(path),
             retrieved_utc=datetime.now(timezone.utc).isoformat(), etag=response.headers.get("ETag"))
    write(sidecar, m)
    return m


def field_file(key, field, base, ranges):
    name = f"{key}_sfc_{field}.grib2"
    p = OLD / "cache/hrrr" / name
    if p.exists() and p.with_suffix(".grib2.json").exists():
        m = json.loads(p.with_suffix(".grib2.json").read_text())
        if m["url"] != base or m["sha256"] != hash_file(p) or m["byte_range"] != list(ranges[field]):
            raise ValueError("Historical HRRR cache does not match this field")
        return p, {**m, "reuse": "historical_step6", "path": rel(p)}
    p = OUT / "cache/hrrr" / name
    return p, {**fetch(base, p, ranges[field]), "reuse": "current_run", "path": rel(p)}


def weather_job(job, polygons):
    t = pd.Timestamp(job["time"])
    key = t.strftime("%Y%m%dT%HZ")
    destination = OUT / "weather" / f"{key}_summary.json"
    if destination.exists():
        return json.loads(destination.read_text())
    url = f"https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{t:%Y%m%d}/conus/hrrr.t{t:%H}z.wrfsfcf00.grib2"
    ip = OLD / "cache/hrrr" / f"{key}_sfc.idx"
    if ip.exists() and ip.with_suffix(".idx.json").exists():
        im = json.loads(ip.with_suffix(".idx.json").read_text())
        if im["sha256"] != hash_file(ip) or im["url"] != url + ".idx":
            raise ValueError("Historical HRRR index identity mismatch")
    else:
        ip = OUT / "cache/hrrr" / f"{key}_sfc.idx"
        im = fetch(url + ".idx", ip)
    ranges = grib_ranges(ip.read_text(), FIELDS)
    values = {c: {} for c in job["cities"]}
    masks, coordinates, downloads, metadata = {}, {}, [], []
    grid_hash = None
    for field in FIELDS:
        p, m = field_file(key, field, url, ranges)
        downloads.append(m)
        payload = p.read_bytes()
        handle = ec.codes_new_from_message(payload)
        try:
            keys = ["shortName", "units", "forecastTime", "stepType", "stepRange", "dataDate", "dataTime",
                    "validityDate", "validityTime", "md5Section3", "numberOfMissing", "totalLength",
                    "discipline", "parameterCategory", "parameterNumber", "typeOfLevel", "level"]
            info = {k: ec.codes_get(handle, k) for k in keys}
            if (info["shortName"] != FIELD_SHORT_NAMES[field] or info["units"] != FIELD_UNITS[field]
                    or info["forecastTime"] != 0 or info["stepType"] != "instant" or str(info["stepRange"]) != "0"):
                raise ValueError("HRRR field units or instantaneous analysis timing differ")
            if (info["dataDate"] != int(t.strftime("%Y%m%d")) or info["dataTime"] != t.hour*100
                    or info["validityDate"] != info["dataDate"] or info["validityTime"] != info["dataTime"]):
                raise ValueError("HRRR reference/validity time mismatch")
            if info["numberOfMissing"] != 0 or info["totalLength"] != len(payload):
                raise ValueError("Missing HRRR values or unexpected message boundary")
            if field == "dswrf" and (info["discipline"], info["parameterCategory"], info["parameterNumber"], info["typeOfLevel"]) != (0, 4, 7, "surface"):
                raise ValueError("Wrong physical radiation parameter")
            if grid_hash is None:
                grid_hash = info["md5Section3"]
                lat = ec.codes_get_array(handle, "latitudes")
                lon = (ec.codes_get_array(handle, "longitudes") + 180) % 360 - 180
                for city in job["cities"]:
                    poly = polygons[city]
                    x0, y0, x1, y1 = poly.bounds
                    near = np.flatnonzero((lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1))
                    idx = near[shapely.covers(poly, shapely.points(lon[near], lat[near]))]
                    if not len(idx):
                        raise ValueError("Empty HRRR domain")
                    masks[city] = idx
                    coordinates[city] = {"latitude": lat[idx], "longitude": lon[idx]}
            elif info["md5Section3"] != grid_hash:
                raise ValueError("HRRR fields have different native grids")
            for city, idx in masks.items():
                a = np.asarray(ec.codes_get_elements(handle, "values", idx.tolist()), dtype=float)
                if not np.isfinite(a).all() or (field in ("t2m", "d2m") and (a <= 0).any()) or (field == "dswrf" and (a < 0).any()):
                    raise ValueError("Invalid hourly domain values")
                values[city][field] = a
            metadata.append({"field": field, **info})
        finally:
            ec.codes_release(handle)
    result = []
    for city, v in values.items():
        v["vpd"] = vpd_kpa(v["t2m"], v["d2m"])
        v["wind_speed"] = np.hypot(v["u10"], v["v10"])
        old_cells = OLD / "weather" / f"{key}_{city}_cells.npz"
        match = None
        if old_cells.exists():
            with np.load(old_cells, allow_pickle=False) as old:
                if not np.array_equal(old["indices"], masks[city]):
                    raise ValueError("New HRRR spatial aggregation differs from the frozen domain")
                for field in ("t2m", "d2m", "u10", "v10", "vpd", "wind_speed"):
                    if not np.allclose(old[field], v[field], atol=1e-12, rtol=0):
                        raise ValueError("Historical hourly weather values failed exact reconciliation")
            match = True
        cellfile = OUT / "weather" / f"{key}_{city}_cells.npz"
        cellfile.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cellfile, indices=masks[city], **coordinates[city], **v)
        result.append(dict(city=city, timestamp_utc=t.isoformat(), n_domain_cells=len(masks[city]),
                           grid_md5=grid_hash, historical_cell_values_reproduced=match,
                           cells_path=rel(cellfile), cells_sha256=hash_file(cellfile),
                           **{name + "_mean": float(a.mean()) for name, a in v.items()}))
    record = dict(time=t.isoformat(), index={**im, "path": rel(ip)}, downloads=downloads, grib_metadata=metadata, rows=result)
    write(destination, record)
    return record


def retrieve():
    cfg = config()
    polygons = domains()
    failures, completed = [], 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(weather_job, job, polygons): job for job in cfg["weather_jobs"]}
        for future in as_completed(futures):
            job = futures[future]
            try:
                future.result()
                completed += 1
            except Exception as error:
                failures.append({"job": job, "type": type(error).__name__, "message": str(error)[:400]})
                write(EXEC / "retrieval_failures.json", failures)
            print(json.dumps({"stage": "weather", "completed": completed, "requested": len(futures), "failures": len(failures)}), flush=True)
    write(EXEC / "retrieval_completion.json", dict(requested=len(cfg["weather_jobs"]), completed=completed, failures=failures))
    if failures:
        raise ValueError("Source/decoding issues remain; do not substitute data")


def assemble():
    cfg = config()
    done = json.loads((EXEC / "retrieval_completion.json").read_text())
    if done["failures"] or done["completed"] != len(cfg["weather_jobs"]):
        raise ValueError("Hourly inputs are incomplete")
    hours, manifest = {}, []
    for job in cfg["weather_jobs"]:
        key = pd.Timestamp(job["time"]).strftime("%Y%m%dT%HZ")
        record = json.loads((OUT / "weather" / f"{key}_summary.json").read_text())
        manifest.append(record)
        for row in record["rows"]:
            if hash_file(ROOT / row["cells_path"]) != row["cells_sha256"]:
                raise ValueError("Hourly cell archive changed")
            hours[(row["city"], pd.Timestamp(row["timestamp_utc"]))] = row
    output, summaries, timing = [], [], []
    field_map = {"t2m_mean": "air_temperature_K", "d2m_mean": "dewpoint_K",
                 "vpd_mean": "VPD_kPa", "wind_speed_mean": "wind_speed_m_s"}
    for original in cfg["passes"]:
        row = dict(original)
        city, orbit = row["city"], int(row["orbit"])
        coord = cfg["coordinates"][city]
        lo, hi, weight = brackets(row["acquisition_utc"])
        a, b = hours[(city, lo)], hours[(city, hi)]
        at, low, high = [sun_at(t, **coord) for t in (row["acquisition_utc"], lo, hi)]
        radiation = interpolate_shortwave(a["dswrf_mean"], b["dswrf_mean"], low["sin_solar_elevation"], high["sin_solar_elevation"], at["sin_solar_elevation"], weight)
        computed = {target: (1-weight)*a[source]+weight*b[source] for source, target in field_map.items()}
        if row["sample_role"] == "main_2023":
            for target, value in computed.items():
                if abs(float(row[target])-value) > 1e-10:
                    raise ValueError("Original 2023 weather does not reproduce: " + target)
        else:
            row.update(computed)
            row["apparent_solar_hour"] = at["apparent_solar_hour"]
        scenes = [r for r in cfg["scene_records"] if r["city"] == city and r["orbit"] == orbit]
        row.update(scene_summary(scenes))
        row.update(geo_binding_acquisition_utc=scenes[0]["geo_binding_acquisition_utc"],
                   geo_binding_minus_model_time_seconds=scenes[0]["geo_binding_minus_model_time_seconds"],
                   pass_time_source="existing model/selection table, retained by user decision")
        row.update(radiation)
        row.update(solar_elevation_deg=at["solar_elevation_deg"], solar_zenith_step1_deg=at["solar_zenith_deg"],
                   sin_solar_elevation=at["sin_solar_elevation"], after_noon=int(at["apparent_solar_hour"] > 12),
                   solar_latitude_deg=coord["latitude"], solar_longitude_deg=coord["longitude"],
                   solar_days_in_year=at["days_in_year"],
                   hrrr_floor_utc=lo.isoformat(), hrrr_ceiling_utc=hi.isoformat(),
                   hrrr_interpolation_weight=weight, shortwave_floor_W_m2=a["dswrf_mean"],
                   shortwave_ceiling_W_m2=b["dswrf_mean"],
                   solar_cosine_floor=low["sin_solar_elevation"], solar_cosine_ceiling=high["sin_solar_elevation"],
                   hrrr_domain_cells=a["n_domain_cells"], hrrr_product="HRRR CONUS wrfsfcf00 analysis",
                   hrrr_shortwave_shortName="sdswrf", hrrr_shortwave_units="W m-2",
                   geolocation_product="ECO_L1B_GEO.002", census_usable_categories="best;good",
                   weather_input_status="complete", geolocation_input_status="exact checksum-bound metadata",
                   rainfall_input_scope="existing 2023 descriptors" if row["sample_role"] == "main_2023" else "not requested for other-year Step1 inputs")
        if a["n_domain_cells"] != b["n_domain_cells"] or a["grid_md5"] != b["grid_md5"]:
            raise ValueError("Bracketing spatial supports differ")
        output.append(row)
        summaries.append({k: row[k] for k in ("city", "orbit", "local_date", "sample_role", "geolocation_categories_by_scene", "geolocation_worst_category", "shortwave_W_m2", "solar_elevation_deg", "sin_solar_elevation", "air_temperature_K", "effect_access_status")})
        timing.append(dict(city=city, orbit=orbit, at=at, floor=low, ceiling=high, weight=weight, radiation=radiation))
    check_holdout_blanks(output)
    # Every inherited field in all sixteen public rows stays exactly as supplied.
    by_key = {(r["city"], str(r["orbit"])): r for r in output}
    for source in csv.DictReader((ROOT / PASS_TABLE).open()):
        updated = by_key[(source["city"], source["orbit"])]
        if any(updated[k] != v for k, v in source.items()):
            raise ValueError("An inherited 2023 pass-table field was changed")
    leading = ["city", "orbit", "local_date", "acquisition_utc", "sample_role", "effect_access_status",
               "source_run_id", "geolocation_categories_by_scene", "geolocation_worst_category", "shortwave_W_m2",
               "sin_solar_elevation", "solar_elevation_deg", "apparent_solar_hour", "after_noon"]
    fields = list(dict.fromkeys(leading + cfg["source_columns"] + sorted(set().union(*(r.keys() for r in output)))))
    PACKET.mkdir(parents=True, exist_ok=True)
    csv_path = PACKET / "pass_inputs_23.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    write(EXEC / "pass_summary_nonthermal.json", summaries)
    write(EXEC / "solar_and_interpolation_audit.json", timing)
    write(EXEC / "hourly_download_manifest.json", manifest)
    write(PACKET / "scene_geolocation_provenance.json", cfg["scene_records"])
    result = dict(status="STEP1_INPUTS_COMPLETE", passes=len(output), main_2023=16, unopened_other_year=7,
                  scene_count=len(cfg["scene_records"]), scene_categories={k: sum(r["category"] == k for r in cfg["scene_records"]) for k in ("best", "good", "suspect", "poor")},
                  complete_radiation_rows=len(output), weather_hours=len(cfg["weather_jobs"]),
                  low_sun_single_ratio_rows=sum("only" in r["shortwave_interpolation_method"] for r in output),
                  all_original_2023_table_fields_preserved=True, other_year_effect_fields_blank=True,
                  new_fits=0, raw_thermal_values_read=False, seven_other_year_effects_opened=False,
                  csv_sha256=hash_file(csv_path), source_and_code_hashes_verified=True)
    write(EXEC / "completion.json", result)
    write(PACKET / "completion.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "retrieve", "assemble"))
    action = parser.parse_args().action
    {"prepare": prepare, "retrieve": retrieve, "assemble": assemble}[action]()
