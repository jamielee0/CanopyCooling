"""Nonthermal Step 6 timing, weather, precipitation and frozen-window helpers."""
import numpy as np
import pandas as pd

WEIGHTS = {27963:.5, 28909:.5, 28192:-.5, 28828:-.25, 29092:-.25}
PASS_COLUMNS = ("city", "orbit", "local_date", "acquisition_utc", "apparent_solar_hour",
                "source_run_id", "view_zenith_p95_deg", "n_cells", "variant")


def timestamp(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None: raise ValueError("Timezone-aware acquisition required")
    return t.tz_convert("UTC")


def brackets(value):
    t = timestamp(value); lo = t.floor("h"); hi = t.ceil("h")
    return lo, hi, 0. if lo == hi else float((t-lo)/(hi-lo))


def interpolate(value, hourly, fields):
    lo, hi, weight = brackets(value)
    if hourly.index.duplicated().any(): raise ValueError("Duplicate weather hours")
    if lo not in hourly.index or hi not in hourly.index: return None
    a, b = hourly.loc[lo, list(fields)].to_numpy(float), hourly.loc[hi, list(fields)].to_numpy(float)
    if not np.isfinite(a).all() or not np.isfinite(b).all(): return None
    return dict(zip(fields, ((1-weight)*a+weight*b).tolist()))


def vpd_kpa(temperature_K, dewpoint_K):
    t, d = np.broadcast_arrays(np.asarray(temperature_K,float), np.asarray(dewpoint_K,float))
    if not np.isfinite(t).all() or not np.isfinite(d).all() or (t<=0).any() or (d<=0).any():
        raise ValueError("Finite Kelvin meteorology required")
    tc, dc = t-273.15, d-273.15
    return np.maximum(0., .6108*np.exp(17.27*tc/(tc+237.3))-.6108*np.exp(17.27*dc/(dc+237.3)))


def rain_hours(value, days):
    if days not in (1,3,7): raise ValueError("Unfrozen rainfall window")
    end = timestamp(value).floor("h")
    return pd.date_range(end-pd.Timedelta(days=days)+pd.Timedelta(hours=1), end, freq="h")


def accumulate_rain(values, times, required, weights):
    """No temporal gaps, negative sentinel replacement or changing spatial support."""
    a = np.asarray(values,float); w = np.asarray(weights,float)
    times = pd.DatetimeIndex(times)
    if times.duplicated().any(): raise ValueError("Duplicate rainfall accumulations")
    if a.shape != (len(times),len(w)) or not np.isfinite(w).all() or (w<=0).any(): raise ValueError("Invalid rainfall shape/weights")
    idx = times.get_indexer(required)
    if (idx<0).any():
        return dict(status="MISSING_HOURLY_PAYLOADS", total_mm=None, complete_cell_fraction=None,
                    required_hours=len(required), available_hours=int((idx>=0).sum()))
    subset = a[idx]
    complete = np.isfinite(subset).all(axis=0) & (subset>=0).all(axis=0)
    coverage = float(w[complete].sum()/w.sum())
    total = float(np.average(subset.sum(axis=0),weights=w)) if complete.all() else None
    return dict(status="COMPLETE_LAST_CLOSED_HOUR_WINDOW" if complete.all() else "INCOMPLETE_SPATIAL_QPE_COVERAGE",
                total_mm=total, complete_cell_fraction=coverage, required_hours=len(required), available_hours=len(required))


def grib_ranges(index_text, field_levels):
    entries=[]
    for line in index_text.strip().splitlines():
        parts=line.split(":")
        if len(parts)<6: raise ValueError("Malformed GRIB index")
        entries.append((int(parts[1]),parts[3],parts[4]))
    if any(b[0]<=a[0] for a,b in zip(entries,entries[1:])): raise ValueError("Nonmonotonic GRIB byte offsets")
    result={}
    for key,(field,level) in field_levels.items():
        found=[i for i,v in enumerate(entries) if v[1:]==(field,level)]
        if len(found)!=1 or found[0]+1==len(entries): raise ValueError("Missing/ambiguous GRIB field boundary")
        i=found[0]; result[key]=(entries[i][0],entries[i+1][0]-1)
    return result


def window_plan(passes):
    p=passes.copy(); p["window_weight"]=[WEIGHTS.get(int(r.orbit),0.) if r.city=="phoenix" else 0. for r in p.itertuples()]
    p["time_arm"]=["morning" if 9.5<=h<=11.5 else "afternoon" if 15<=h<=18 else "outside_windows" for h in p.apparent_solar_hour]
    for r in p[p.window_weight.ne(0)].itertuples():
        if r.time_arm != ("afternoon" if r.window_weight>0 else "morning"): raise ValueError("Frozen date outside its specified window")
    chosen=p[p.window_weight.ne(0)]
    if len(chosen)!=5 or set(chosen.orbit)!=set(WEIGHTS): raise ValueError("Frozen five-date schedule changed")
    if not np.isclose(chosen.window_weight.clip(lower=0).sum(),1) or not np.isclose(chosen.window_weight.clip(upper=0).sum(),-1): raise ValueError("Unbalanced arms")
    return p


def assert_nonthermal_columns(columns):
    if not set(columns).issubset(PASS_COLUMNS): raise ValueError("Unapproved Step6 input table column")


def solar_geometry(latitude_deg, solar_hour, day_of_year, days_in_year=365):
    """Harmonic declination plus supplied apparent solar time, geographic centroid."""
    gamma=2*np.pi/days_in_year*(day_of_year-1+(solar_hour-12)/24)
    decl=(.006918-.399912*np.cos(gamma)+.070257*np.sin(gamma)-.006758*np.cos(2*gamma)
          +.000907*np.sin(2*gamma)-.002697*np.cos(3*gamma)+.001480*np.sin(3*gamma))
    phi=np.deg2rad(latitude_deg); hour=np.deg2rad(15*(solar_hour-12))
    zenith=np.rad2deg(np.arccos(np.clip(np.sin(phi)*np.sin(decl)+np.cos(phi)*np.cos(decl)*np.cos(hour),-1,1)))
    azimuth=(np.rad2deg(np.arctan2(np.sin(hour),np.cos(hour)*np.sin(phi)-np.tan(decl)*np.cos(phi)))+180)%360
    return float(zenith),float(azimuth)
