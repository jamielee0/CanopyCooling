"""Outcome-blind Task 2A freeze and preflight for the D0056 time-of-day branch.

This module is deliberately limited to TOML/CSV/JSON metadata.  It never opens a
raster, follows a data URL, downloads an asset, or reads a thermal value.  The
generic interaction Task-2 guardrail remains untouched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import tomllib
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "v2_task2_time_of_day.toml"
DECISION_LOG = REPO_ROOT / "docs" / "v2" / "DECISION_LOG.md"

EXPECTED_GATE = "PASS_TIME_OF_DAY_ONLY"
EXPECTED_PROFILE_GATE = "PASS_D0056_TIME_OF_DAY_ONLY_TASK1"
EXPECTED_PROFILE = "D0056_time_of_day_only"
EXPECTED_SCOPE = "time_of_day_only_archive_available_D0047"
EXPECTED_HOLDOUT = "minneapolis_st_paul"
EXPECTED_DEVELOPMENT_CITIES = ("atlanta", "los_angeles", "miami", "phoenix")

FROZEN_DECISIONS = (
    "cross_city_scope_status",
    "holdout_eligibility_rule_status",
    "holdout_selection_status",
    "collection_chain_status",
    "time_strata_status",
    "scene_pixel_qa_status",
    "meteorology_status",
    "optical_landcover_status",
    "classification_matching_status",
    "analysis_schema_status",
    "storage_status",
)

REQUIRED_LOCO_GATE_FIELDS: dict[str, Any] = {
    "full_panel_primary_contrast_planning_n": 72,
    "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
    "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
    "all_permitted_non_phoenix_holdouts_supported": True,
}

CMR_BASE = "https://cmr.earthdata.nasa.gov/search"
_LSTE_ID_RE = re.compile(
    r"^ECOv002_L2T_LSTE_(?P<orbit>\d{5})_(?P<scene>\d{3})_"
    r"(?P<tile>[0-9A-Z]{5})_(?P<acquisition>\d{8}T\d{6})_"
    r"(?P<build>\d{4})_(?P<revision>\d{2})(?:\.zip)?$"
)
_ORBIT_PRODUCT_RE = re.compile(
    r"^ECOv002_(?P<short>L[234]T_[A-Z_]+)_(?P<orbit>\d{5})_"
    r"(?P<scene>\d{3})_(?P<tile>[0-9A-Z]{5})_"
    r"(?P<acquisition>\d{8}T\d{6})_(?P<build>\d{4})_"
    r"(?P<revision>\d{2})$"
)
_STARS_RE = re.compile(
    r"^ECOv002_L2T_STARS_(?P<tile>[0-9A-Z]{5})_(?P<date>\d{8})_"
    r"(?P<build>\d{4})_(?P<revision>\d{2})$"
)

PRODUCTS: tuple[dict[str, Any], ...] = (
    {
        "family": "LSTE",
        "product": "ECO_L2T_LSTE.002",
        "layers": "LST|LST_err|EmisWB|height|view_zenith|QC|cloud|water",
        "bytes_per_pixel_upper": 24,
        "role": "primary_native_temperature_and_QA",
    },
    {
        "family": "STARS",
        "product": "ECO_L2T_STARS.002",
        "layers": "NDVI|NDVI-UQ|albedo|albedo-UQ",
        "bytes_per_pixel_upper": 16,
        "role": "primary_same_pass_optical_and_albedo",
    },
    {
        "family": "SEB",
        "product": "ECO_L3T_SEB.002",
        "layers": "Rg|Rn|cloud|water",
        "bytes_per_pixel_upper": 10,
        "role": "primary_radiation",
    },
    {
        "family": "JET",
        "product": "ECO_L3T_JET.002",
        "layers": (
            "PTJPLSMinst|STICinst|MOD16inst|BESSinst|ETinstUncertainty|"
            "PTJPLSMcanopy|PTJPLSMinterception|PTJPLSMsoil|cloud|water"
        ),
        "bytes_per_pixel_upper": 29,
        "role": "primary_four_member_ET_and_components",
    },
    {
        "family": "ESI",
        "product": "ECO_L4T_ESI.002",
        "layers": "ESI|PET|cloud|water",
        "bytes_per_pixel_upper": 10,
        "role": "primary_evaporative_stress_consistency",
    },
    {
        "family": "ET_ALEXI",
        "product": "ECO_L3T_ET_ALEXI.002",
        "layers": "ETdaily|ETdailyUncertainty",
        "bytes_per_pixel_upper": 8,
        "role": "second_family_daily_ET_sensitivity",
    },
    {
        "family": "HLS_PREPASS",
        "product": "HLSL30.002|HLSS30.002",
        "layers": "red|nir|swir1|Fmask",
        "bytes_per_pixel_upper": 7,
        "role": "prepass_and_season_to_date_optical",
    },
)


@dataclass(frozen=True)
class Blocker:
    code: str
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    ready: bool
    blockers: tuple[Blocker, ...]
    task1_gate_path: str
    task1_gate_value: str
    holdout_city: str
    development_cities: tuple[str, ...]
    free_bytes: int
    projected_peak_bytes: int
    required_free_bytes: int
    thermal_files_opened: int = 0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = [asdict(item) for item in self.blockers]
        payload["development_cities"] = list(self.development_cities)
        return payload


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with Path(path).expanduser().resolve().open("rb") as handle:
        return tomllib.load(handle)


def _repo_path(root: Path, value: str) -> Path:
    if Path(value).is_absolute():
        raise ValueError(f"repository path must be relative: {value}")
    result = (root / value).resolve()
    result.relative_to(root)
    return result


def _truth(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().eq("true")


def _holdout_ranking(config: Mapping[str, Any], counts: pd.DataFrame) -> pd.DataFrame:
    rule = config["holdout"]
    detail = counts.loc[counts["count_scope"].eq("detail")].copy()
    detail["n_usable_passes"] = pd.to_numeric(detail["n_usable_passes"], errors="raise")
    detail["expected_usable_pass_equivalents"] = pd.to_numeric(
        detail["expected_usable_pass_equivalents"], errors="raise"
    )
    records: list[dict[str, Any]] = []
    for city in rule["candidate_cities"]:
        frame = detail.loc[detail["city"].eq(city)].copy()
        if frame.empty:
            raise ValueError(f"holdout candidate {city!r} has no Step-2 count evidence")
        by_year = frame.groupby("year", sort=True)["n_usable_passes"].sum()
        by_stratum = frame.groupby("time_stratum", sort=True).agg(
            physical=("n_usable_passes", "sum"),
            expected=("expected_usable_pass_equivalents", "sum"),
        )
        positive_years = int((by_year > 0).sum())
        positive_strata = int((by_stratum["physical"] > 0).sum())
        minimum_physical = int(by_stratum["physical"].min())
        minimum_expected = float(by_stratum["expected"].min())
        positive_year_strata = int((frame["n_usable_passes"] > 0).sum())
        eligible = bool(
            positive_years >= int(rule["required_positive_years"])
            and positive_strata >= int(rule["required_positive_strata"])
            and minimum_physical >= int(rule["minimum_physical_passes_per_stratum"])
            and minimum_expected
            >= float(rule["minimum_expected_pass_equivalents_per_stratum"])
        )
        reasons: list[str] = []
        if positive_years < int(rule["required_positive_years"]):
            reasons.append("insufficient_positive_years")
        if positive_strata < int(rule["required_positive_strata"]):
            reasons.append("insufficient_positive_strata")
        if minimum_physical < int(rule["minimum_physical_passes_per_stratum"]):
            reasons.append("minimum_physical_stratum_support")
        if minimum_expected < float(rule["minimum_expected_pass_equivalents_per_stratum"]):
            reasons.append("minimum_expected_stratum_support")
        records.append(
            {
                "city": city,
                "eligible": eligible,
                "positive_years": positive_years,
                "positive_strata": positive_strata,
                "positive_city_year_strata": positive_year_strata,
                "minimum_stratum_physical_passes": minimum_physical,
                "minimum_stratum_expected_pass_equivalents": minimum_expected,
                "total_physical_passes": int(frame["n_usable_passes"].sum()),
                "total_expected_pass_equivalents": float(
                    frame["expected_usable_pass_equivalents"].sum()
                ),
                "ineligibility_reasons": "|".join(reasons),
                "evidence_origin": "empirical_nonthermal_D0047_step2",
                "thermal_outcome_used": False,
            }
        )
    result = pd.DataFrame.from_records(records)
    result = result.sort_values(
        by=[
            "eligible",
            "positive_city_year_strata",
            "minimum_stratum_expected_pass_equivalents",
            "total_expected_pass_equivalents",
            "total_physical_passes",
            "city",
        ],
        ascending=[False, False, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    result.insert(0, "rank", range(1, len(result) + 1))
    result["selected_holdout"] = result["city"].eq(rule["selected_city"])
    winner = str(result.iloc[0]["city"])
    if winner != rule["selected_city"] or not bool(result.iloc[0]["eligible"]):
        raise ValueError(
            f"frozen holdout {rule['selected_city']!r} does not win the quality-only rule; "
            f"computed winner={winner!r}"
        )
    return result


def _scene_inventory(config: Mapping[str, Any], catalogue: pd.DataFrame) -> dict[str, Any]:
    required = {
        "city",
        "year",
        "scene_key",
        "official_scene_granule_ids",
        "quality_candidate_pre_cloud_geometry_only",
        "lst_opened",
        "thermal_opened",
        "record_2026_opened",
    }
    missing = required.difference(catalogue.columns)
    if missing:
        raise ValueError(f"scene catalogue missing columns: {sorted(missing)}")
    for column in ("lst_opened", "thermal_opened", "record_2026_opened"):
        if _truth(catalogue[column]).any():
            raise ValueError(f"prethermal evidence is invalid: {column}=true")
    physical = catalogue.loc[_truth(catalogue["quality_candidate_pre_cloud_geometry_only"])].copy()
    development = physical.loc[physical["city"].isin(config["task2"]["development_cities"])].copy()
    development["tile_associations"] = development["official_scene_granule_ids"].fillna("").map(
        lambda value: len([item for item in str(value).split("|") if item])
    )
    if (development["tile_associations"] <= 0).any():
        raise ValueError("a development pass lacks official tile identifiers")
    by_batch = development.groupby(["city", "year"], sort=True).agg(
        passes=("scene_key", "nunique"),
        tile_associations=("tile_associations", "sum"),
    )
    return {
        "development_physical_passes": int(development["scene_key"].nunique()),
        "development_pass_tile_associations": int(development["tile_associations"].sum()),
        "maximum_city_year_pass_tile_associations": int(by_batch["tile_associations"].max()),
        "maximum_city_year_batch": "|".join(
            str(part) for part in by_batch["tile_associations"].idxmax()
        ),
        "city_year_batch_count": int(len(by_batch)),
    }


def _expected_pass_tile_associations(
    config: Mapping[str, Any], catalogue: pd.DataFrame
) -> pd.DataFrame:
    """Expand the frozen D0047 pass catalogue to one expected LSTE tile per row."""

    required = {
        "city",
        "year",
        "scene_key",
        "time_stratum",
        "official_scene_granule_ids",
        "quality_candidate_pre_cloud_geometry_only",
    }
    missing = required.difference(catalogue.columns)
    if missing:
        raise ValueError(f"scene catalogue missing CMR-census columns: {sorted(missing)}")
    selected = catalogue.loc[
        _truth(catalogue["quality_candidate_pre_cloud_geometry_only"])
        & catalogue["city"].isin(config["task2"]["development_cities"])
    ].copy()
    rows: list[dict[str, Any]] = []
    for source_row in selected.to_dict(orient="records"):
        identities = [
            item.strip()
            for item in str(source_row["official_scene_granule_ids"] or "").split("|")
            if item.strip()
        ]
        if not identities:
            raise ValueError(f"{source_row['scene_key']}: no official LSTE tile identities")
        for lste_id in identities:
            parsed = _LSTE_ID_RE.fullmatch(lste_id)
            if parsed is None:
                raise ValueError(f"unrecognised frozen LSTE producer identity: {lste_id}")
            values = parsed.groupdict()
            rows.append(
                {
                    "city": source_row["city"],
                    "year": int(source_row["year"]),
                    "scene_key": source_row["scene_key"],
                    "time_stratum": source_row["time_stratum"],
                    "expected_lste_producer_id": lste_id.removesuffix(".zip"),
                    "orbit": values["orbit"],
                    "scene": values["scene"],
                    "tile": values["tile"],
                    "acquisition_token": values["acquisition"],
                    "acquisition_date": values["acquisition"][:8],
                }
            )
    result = pd.DataFrame.from_records(rows)
    result.insert(0, "association_id", range(1, len(result) + 1))
    if result.empty:
        raise ValueError("CMR census has no eligible development pass/tile associations")
    if result["expected_lste_producer_id"].duplicated().any():
        duplicates = sorted(
            result.loc[
                result["expected_lste_producer_id"].duplicated(keep=False),
                "expected_lste_producer_id",
            ].unique()
        )
        raise ValueError(f"duplicate expected LSTE identities: {duplicates[:3]}")
    return result


def _public_cmr_json(url: str, *, timeout_seconds: int = 60) -> dict[str, Any]:
    """Read public CMR JSON only; no Earthdata token or data-object URL is used."""

    if not url.startswith(f"{CMR_BASE}/"):
        raise ValueError("public CMR requester refused a non-CMR URL")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "TreeProject-D0057-public-metadata-census/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("CMR response is not a JSON object")
            return payload
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"public CMR metadata request failed after four attempts: {last_error}")


def _cmr_feed_entries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    feed = payload.get("feed")
    if not isinstance(feed, Mapping):
        raise ValueError("CMR response lacks a feed object")
    entries = feed.get("entry", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ValueError("CMR feed entry is not a list of objects")
    return entries


def _cmr_products(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = config.get("public_cmr_census", {}).get("products", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("public_cmr_census.products is missing")
    required = {"family", "short_name", "version", "concept_id", "core"}
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or required.difference(row):
            raise ValueError("a public CMR product definition is incomplete")
        copied = dict(row)
        if copied["version"] != "002":
            raise ValueError(f"{copied['family']}: only frozen Collection 002 is permitted")
        result.append(copied)
    expected = {"LSTE", "STARS", "SEB", "JET", "ESI", "ET_ALEXI"}
    found = {str(row["family"]) for row in result}
    if found != expected:
        raise ValueError(f"CMR product families changed: expected={sorted(expected)} found={sorted(found)}")
    return result


def _cmr_pattern(product: Mapping[str, Any], expected: Mapping[str, Any]) -> str:
    family = str(product["family"])
    if family == "STARS":
        return (
            f"ECOv002_L2T_STARS_{expected['tile']}_{expected['acquisition_date']}_*"
        )
    product_token = str(product["short_name"]).removeprefix("ECO_")
    return (
        f"ECOv002_{product_token}_{expected['orbit']}_{expected['scene']}_"
        f"{expected['tile']}_{expected['acquisition_token']}_*"
    )


def _normalise_cmr_time(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _cmr_entry_key(family: str, entry: Mapping[str, Any]) -> tuple[str, ...] | None:
    producer_id = str(entry.get("producer_granule_id") or entry.get("title") or "")
    if family == "STARS":
        parsed = _STARS_RE.fullmatch(producer_id)
        domains = entry.get("orbit_calculated_spatial_domains", [])
        if parsed is None or not isinstance(domains, list):
            return None
        orbits = {
            str(item.get("start_orbit_number", "")).zfill(5)
            for item in domains
            if isinstance(item, Mapping) and item.get("start_orbit_number") is not None
        }
        acquisition = _normalise_cmr_time(entry.get("time_start"))
        if len(orbits) != 1 or not acquisition:
            return None
        return (next(iter(orbits)), parsed.group("tile"), acquisition)
    parsed = _ORBIT_PRODUCT_RE.fullmatch(producer_id)
    if parsed is None:
        return None
    values = parsed.groupdict()
    return (values["orbit"], values["scene"], values["tile"], values["acquisition"])


def _expected_match_key(family: str, row: Mapping[str, Any]) -> tuple[str, ...]:
    if family == "STARS":
        return (str(row["orbit"]), str(row["tile"]), str(row["acquisition_token"]))
    return (
        str(row["orbit"]),
        str(row["scene"]),
        str(row["tile"]),
        str(row["acquisition_token"]),
    )


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _collection_metadata(
    product: Mapping[str, Any], requester: Any
) -> tuple[dict[str, Any], int]:
    query = urlencode(
        {
            "short_name": product["short_name"],
            "version": product["version"],
            "page_size": 10,
        }
    )
    entries = _cmr_feed_entries(requester(f"{CMR_BASE}/collections.json?{query}"))
    exact = [
        item
        for item in entries
        if item.get("short_name") == product["short_name"]
        and str(item.get("version_id")) == str(product["version"])
    ]
    if len(exact) != 1:
        raise ValueError(
            f"{product['family']}: expected one exact public CMR collection, found {len(exact)}"
        )
    entry = exact[0]
    if entry.get("id") != product["concept_id"]:
        raise ValueError(
            f"{product['family']}: concept ID changed from {product['concept_id']} "
            f"to {entry.get('id')}"
        )
    safe = {
        "family": product["family"],
        "short_name": entry.get("short_name"),
        "version": entry.get("version_id"),
        "concept_id": entry.get("id"),
        "title": entry.get("title"),
        "time_start": entry.get("time_start"),
        "time_end": entry.get("time_end"),
        "updated": entry.get("updated"),
        "data_center": entry.get("data_center"),
        "cloud_hosted": entry.get("cloud_hosted"),
        "online_access_flag": entry.get("online_access_flag"),
        "core": bool(product["core"]),
    }
    return safe, 1


def _granule_metadata_for_product(
    product: Mapping[str, Any],
    expected: pd.DataFrame,
    requester: Any,
    *,
    pattern_batch_size: int,
) -> tuple[list[dict[str, Any]], int, int]:
    patterns = sorted({_cmr_pattern(product, row) for row in expected.to_dict(orient="records")})
    entries_by_id: dict[str, dict[str, Any]] = {}
    request_count = 0
    unparsed_count = 0
    for batch in _chunks(patterns, pattern_batch_size):
        parameters: list[tuple[str, Any]] = [
            ("collection_concept_id", product["concept_id"]),
            ("page_size", 2000),
            ("options[producer_granule_id][pattern]", "true"),
        ]
        parameters.extend(("producer_granule_id[]", pattern) for pattern in batch)
        url = f"{CMR_BASE}/granules.json?{urlencode(parameters, doseq=True)}"
        entries = _cmr_feed_entries(requester(url))
        request_count += 1
        if len(entries) >= 2000:
            raise ValueError(
                f"{product['family']}: a CMR batch reached page_size=2000; census is incomplete"
            )
        for entry in entries:
            producer_id = str(entry.get("producer_granule_id") or entry.get("title") or "")
            if producer_id:
                entries_by_id[producer_id] = entry

    indexed: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for entry in entries_by_id.values():
        key = _cmr_entry_key(str(product["family"]), entry)
        if key is None:
            unparsed_count += 1
            continue
        indexed.setdefault(key, []).append(entry)

    rows: list[dict[str, Any]] = []
    for expected_row in expected.to_dict(orient="records"):
        key = _expected_match_key(str(product["family"]), expected_row)
        matches = sorted(
            indexed.get(key, []),
            key=lambda item: str(item.get("producer_granule_id") or item.get("title") or ""),
        )
        match_ids = [
            str(item.get("producer_granule_id") or item.get("title") or "")
            for item in matches
        ]
        sizes: list[float] = []
        for item in matches:
            try:
                sizes.append(float(item.get("granule_size")))
            except (TypeError, ValueError):
                continue
        rows.append(
            {
                **expected_row,
                "family": product["family"],
                "short_name": product["short_name"],
                "collection_version": product["version"],
                "collection_concept_id": product["concept_id"],
                "core_product": bool(product["core"]),
                "query_pattern": _cmr_pattern(product, expected_row),
                "match_count": len(matches),
                "match_status": (
                    "exact_one" if len(matches) == 1 else "missing" if not matches else "ambiguous"
                ),
                "matched_producer_granule_ids": "|".join(match_ids),
                "matched_granule_size_mb": sizes[0] if len(matches) == 1 and sizes else None,
                "thermal_or_science_value_opened": False,
                "data_object_url_followed": False,
            }
        )
    return rows, request_count, unparsed_count


def _normalise_imported_collection(entry: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    result["id"] = result.get("id", result.get("concept_id"))
    result["version_id"] = str(result.get("version_id", result.get("version", "")))
    return result


def _normalise_imported_granule(entry: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    if not result.get("collection_concept_id") and result.get("concept_id"):
        result["collection_concept_id"] = result["concept_id"]
    if not result.get("producer_granule_id") and result.get("title"):
        result["producer_granule_id"] = result["title"]
    domains = result.get("orbit_calculated_spatial_domains")
    if isinstance(domains, str) and domains.strip():
        try:
            result["orbit_calculated_spatial_domains"] = json.loads(domains)
        except json.JSONDecodeError:
            result["orbit_calculated_spatial_domains"] = []
    if not result.get("orbit_calculated_spatial_domains") and result.get(
        "start_orbit_number"
    ):
        result["orbit_calculated_spatial_domains"] = [
            {
                "start_orbit_number": str(result["start_orbit_number"]),
                "stop_orbit_number": str(
                    result.get("stop_orbit_number", result["start_orbit_number"])
                ),
            }
        ]
    return result


def _entries_from_imported_json(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collections: list[dict[str, Any]] = []
    granules: list[dict[str, Any]] = []

    def visit(value: Any, forced_kind: str | None = None) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, forced_kind)
            return
        if not isinstance(value, Mapping):
            return
        if "collections" in value or "granules" in value:
            visit(value.get("collections", []), "collection")
            visit(value.get("granules", []), "granule")
            return
        feed = value.get("feed")
        if isinstance(feed, Mapping) and isinstance(feed.get("entry"), list):
            visit(feed["entry"], forced_kind)
            return
        kind = forced_kind
        if kind is None:
            kind = "granule" if value.get("producer_granule_id") else "collection"
        if kind == "granule":
            granules.append(_normalise_imported_granule(value))
        else:
            collections.append(_normalise_imported_collection(value))

    visit(payload)
    return collections, granules


def _entries_from_imported_csv(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frame = pd.read_csv(path, dtype=str).fillna("")
    if "record_type" not in frame.columns:
        raise ValueError("imported CMR CSV requires record_type=collection or granule")
    collections: list[dict[str, Any]] = []
    granules: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        kind = str(row.pop("record_type", "")).strip().lower()
        cleaned = {key: value for key, value in row.items() if value != ""}
        if kind == "collection":
            collections.append(_normalise_imported_collection(cleaned))
        elif kind == "granule":
            granules.append(_normalise_imported_granule(cleaned))
        else:
            raise ValueError(f"invalid imported CMR CSV record_type: {kind!r}")
    return collections, granules


def imported_cmr_requester(path: str | Path) -> Any:
    """Create a network-free requester from official CMR JSON or normalized CSV.

    JSON can be ``{"collections": [...], "granules": [...]}``, a list of raw
    CMR feed responses, or one raw CMR feed response.  CSV requires a
    ``record_type`` column and the native CMR field names used by the matcher.
    Data/browse links, if present in raw JSON, are ignored and never followed.
    """

    source = Path(path).expanduser().resolve()
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        collections, granules = _entries_from_imported_json(payload)
    elif source.suffix.lower() == ".csv":
        collections, granules = _entries_from_imported_csv(source)
    else:
        raise ValueError("imported CMR metadata must be .json or .csv")
    if not collections:
        raise ValueError("imported CMR metadata contains no collection records")
    if not granules:
        raise ValueError("imported CMR metadata contains no granule records")

    def requester(url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("collections.json"):
            short_name = query.get("short_name", [""])[0]
            version = query.get("version", [""])[0]
            matches = [
                item
                for item in collections
                if item.get("short_name") == short_name
                and str(item.get("version_id")) == str(version)
            ]
            return {"feed": {"entry": matches}}
        if parsed.path.endswith("granules.json"):
            concept_id = query.get("collection_concept_id", [""])[0]
            patterns = query.get("producer_granule_id[]", []) or query.get(
                "producer_granule_id", []
            )
            matches = []
            for item in granules:
                producer_id = str(
                    item.get("producer_granule_id") or item.get("title") or ""
                )
                if item.get("collection_concept_id") != concept_id:
                    continue
                if patterns and not any(fnmatchcase(producer_id, pattern) for pattern in patterns):
                    continue
                matches.append(item)
            return {"feed": {"entry": matches}}
        raise ValueError(f"imported CMR requester refused unsupported path: {parsed.path}")

    return requester


def run_public_cmr_census(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    repo_root: str | Path = REPO_ROOT,
    requester: Any = _public_cmr_json,
    imported_metadata_path: str | Path | None = None,
) -> dict[str, Any]:
    """Census public NASA CMR metadata for every eligible development pass/tile.

    The operation performs collection/granule metadata searches only.  It does
    not use Earthdata credentials, preserve/follow asset URLs, or open arrays.
    """

    root = Path(repo_root).expanduser().resolve()
    config_path = Path(config_path).expanduser().resolve()
    config = load_config(config_path)
    settings = config["public_cmr_census"]
    catalogue_path = _repo_path(root, config["evidence"]["scene_catalogue"])
    catalogue = pd.read_csv(catalogue_path, low_memory=False)
    expected = _expected_pass_tile_associations(config, catalogue)
    products = _cmr_products(config)

    collection_rows: list[dict[str, Any]] = []
    census_rows: list[dict[str, Any]] = []
    request_count = 0
    unparsed_count = 0
    for product in products:
        collection, used = _collection_metadata(product, requester)
        collection_rows.append(collection)
        request_count += used
        rows, used, unparsed = _granule_metadata_for_product(
            product,
            expected,
            requester,
            pattern_batch_size=int(settings["pattern_batch_size"]),
        )
        census_rows.extend(rows)
        request_count += used
        unparsed_count += unparsed

    census = pd.DataFrame.from_records(census_rows)
    summary_rows: list[dict[str, Any]] = []
    for family, frame in census.groupby("family", sort=True):
        exact = int(frame["match_status"].eq("exact_one").sum())
        expected_n = int(len(frame))
        product = next(item for item in products if item["family"] == family)
        summary_rows.append(
            {
                "family": family,
                "short_name": product["short_name"],
                "core_product": bool(product["core"]),
                "expected_associations": expected_n,
                "exact_one_matches": exact,
                "missing_matches": int(frame["match_status"].eq("missing").sum()),
                "ambiguous_matches": int(frame["match_status"].eq("ambiguous").sum()),
                "match_fraction": exact / expected_n,
                "cmr_reported_total_size_mb": float(
                    pd.to_numeric(frame["matched_granule_size_mb"], errors="coerce").sum()
                ),
            }
        )
    summary = pd.DataFrame.from_records(summary_rows).sort_values("family").reset_index(drop=True)
    threshold = float(settings["minimum_core_match_fraction"])
    core_pass = bool(
        (summary.loc[summary["core_product"], "match_fraction"] >= threshold).all()
    )
    et_row = summary.loc[summary["family"].eq("ET_ALEXI")].iloc[0]
    et_role = (
        "AVAILABLE_SECONDARY_SENSITIVITY_ONLY_NOT_CORE"
        if float(et_row["match_fraction"]) >= threshold
        else "DEMOTED_AVAILABILITY_LIMITED_OPTIONAL_STEP5_NOT_CORE"
    )

    census_path = _repo_path(root, settings["match_census_output"])
    summary_path = _repo_path(root, settings["match_summary_output"])
    collections_path = _repo_path(root, settings["collection_inventory_output"])
    record_path = _repo_path(root, settings["census_record_output"])
    _write_csv(census, census_path)
    _write_csv(summary, summary_path)
    collections_payload = {
        "schema_version": 1,
        "queried_utc": datetime.now(timezone.utc).isoformat(),
        "source": "NASA_CMR_PUBLIC_METADATA",
        "collections": collection_rows,
        "credentials_used": False,
        "data_object_urls_followed": 0,
        "thermal_or_science_values_opened": 0,
    }
    collections_path.parent.mkdir(parents=True, exist_ok=True)
    collections_path.write_text(
        json.dumps(collections_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    record: dict[str, Any] = {
        "schema_version": 1,
        "decision_id": config["task2"]["decision_id"],
        "analysis_profile": config["task2"]["analysis_profile"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": (
            "PASS_CORE_PRODUCT_AVAILABILITY" if core_pass else "STOP_CORE_PRODUCT_AVAILABILITY"
        ),
        "minimum_core_match_fraction": threshold,
        "expected_development_pass_tile_associations": int(len(expected)),
        "product_summaries": summary.to_dict(orient="records"),
        "et_alexi_role": et_role,
        "public_cmr_request_count": request_count,
        "metadata_acquisition_mode": (
            "IMPORTED_OFFICIAL_CMR_RESPONSE" if imported_metadata_path else "LIVE_PUBLIC_CMR"
        ),
        "unparsed_cmr_granule_count": unparsed_count,
        "credentials_used": False,
        "data_object_urls_followed": 0,
        "thermal_or_science_values_opened": 0,
        "holdout_included": False,
        "record_2026_included": False,
        "source_scene_catalogue_sha256": sha256_file(catalogue_path),
        "configuration_sha256": sha256_file(config_path),
        "artifact_hashes": {
            str(census_path.relative_to(root)): sha256_file(census_path),
            str(summary_path.relative_to(root)): sha256_file(summary_path),
            str(collections_path.relative_to(root)): sha256_file(collections_path),
        },
    }
    if imported_metadata_path is not None:
        imported = Path(imported_metadata_path).expanduser().resolve()
        try:
            relative_imported = imported.relative_to(root)
        except ValueError as exc:
            raise ValueError("imported CMR metadata must be stored inside the repository") from exc
        record["imported_metadata_path"] = str(relative_imported)
        record["imported_metadata_sha256"] = sha256_file(imported)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def run_imported_public_cmr_census(
    imported_metadata_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    source = Path(imported_metadata_path).expanduser().resolve()
    return run_public_cmr_census(
        config_path,
        repo_root=repo_root,
        requester=imported_cmr_requester(source),
        imported_metadata_path=source,
    )


def _product_and_storage_tables(
    config: Mapping[str, Any], scene_facts: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    tile_pixels = 1568 * 1568
    total_associations = int(scene_facts["development_pass_tile_associations"])
    max_batch = int(scene_facts["maximum_city_year_pass_tile_associations"])
    hls_cap = int(config["optical_landcover"]["prepass_max_acquisitions_per_pass_tile"])
    product_rows: list[dict[str, Any]] = []
    storage_rows: list[dict[str, Any]] = []
    for definition in PRODUCTS:
        multiplier = hls_cap if definition["family"] == "HLS_PREPASS" else 1
        total_objects = total_associations * multiplier
        max_batch_objects = max_batch * multiplier
        total_upper = total_objects * tile_pixels * int(definition["bytes_per_pixel_upper"])
        batch_upper = max_batch_objects * tile_pixels * int(
            definition["bytes_per_pixel_upper"]
        )
        product_rows.append(
            {
                **definition,
                "collection_version": "002",
                "primary_chain": definition["family"] != "ET_ALEXI",
                "official_source": config["collection"]["official_tiled_guide"],
                "metadata_audit_before_value_open": True,
                "thermal_value_opened": False,
            }
        )
        storage_rows.append(
            {
                "family": definition["family"],
                "product": definition["product"],
                "tile_rows": 1568,
                "tile_columns": 1568,
                "bytes_per_pixel_uncompressed_upper": definition["bytes_per_pixel_upper"],
                "estimated_object_count_upper": total_objects,
                "maximum_batch_object_count_upper": max_batch_objects,
                "full_archive_uncompressed_bytes_upper": total_upper,
                "maximum_batch_uncompressed_bytes_upper": batch_upper,
                "storage_basis": (
                    "official_1568x1568_tile_shape_and_layer_dtypes_x_"
                    "D0047_pass_tile_associations"
                ),
                "source_values_opened": False,
            }
        )
    products = pd.DataFrame.from_records(product_rows)
    storage = pd.DataFrame.from_records(storage_rows)
    largest = storage.sort_values(
        "maximum_batch_uncompressed_bytes_upper", ascending=False, kind="mergesort"
    ).iloc[0]
    calculated_peak = int(largest["maximum_batch_uncompressed_bytes_upper"] * 1.5) + 512 * 1024**2
    configured_peak = int(config["storage"]["projected_peak_bytes"])
    if configured_peak < calculated_peak:
        raise ValueError(
            f"configured peak {configured_peak} is below metadata-only bound {calculated_peak}"
        )
    reserve = int(config["storage"]["minimum_reserve_bytes"])
    multiplier = float(config["storage"]["headroom_multiplier"])
    storage_summary = {
        "tile_pixels": tile_pixels,
        "largest_batch_family": str(largest["family"]),
        "largest_batch_uncompressed_bytes_upper": int(
            largest["maximum_batch_uncompressed_bytes_upper"]
        ),
        "calculated_peak_floor_bytes": calculated_peak,
        "configured_projected_peak_bytes": configured_peak,
        "headroom_multiplier": multiplier,
        "minimum_reserve_bytes": reserve,
        "required_free_bytes": int(configured_peak * multiplier) + reserve,
    }
    return products, storage, storage_summary


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def _validated_public_cmr_census(
    config: Mapping[str, Any],
    *,
    config_path: Path,
    root: Path,
    expected_associations: int | None = None,
) -> tuple[Path, dict[str, Any]]:
    settings = config["public_cmr_census"]
    record_path = _repo_path(root, settings["census_record_output"])
    record = _read_json(record_path)
    if record is None:
        raise ValueError(f"mandatory public CMR census record is missing: {record_path}")
    if record.get("status") != "PASS_CORE_PRODUCT_AVAILABILITY":
        raise ValueError(f"public CMR core-product gate is {record.get('status')!r}")
    if record.get("decision_id") != config["task2"]["decision_id"]:
        raise ValueError("public CMR census is not bound to D0057")
    if record.get("configuration_sha256") != sha256_file(config_path):
        raise ValueError("public CMR census configuration hash is stale")
    catalogue_path = _repo_path(root, config["evidence"]["scene_catalogue"])
    if record.get("source_scene_catalogue_sha256") != sha256_file(catalogue_path):
        raise ValueError("public CMR census scene-catalogue hash is stale")
    acquisition_mode = record.get("metadata_acquisition_mode")
    if acquisition_mode == "IMPORTED_OFFICIAL_CMR_RESPONSE":
        imported_path = _repo_path(root, str(record.get("imported_metadata_path", "")))
        if sha256_file(imported_path) != record.get("imported_metadata_sha256"):
            raise ValueError("imported official CMR response hash is stale")
    elif acquisition_mode != "LIVE_PUBLIC_CMR":
        raise ValueError("public CMR census acquisition mode is missing or invalid")
    if expected_associations is not None and int(
        record.get("expected_development_pass_tile_associations", -1)
    ) != int(expected_associations):
        raise ValueError("public CMR census association count changed")
    if float(record.get("minimum_core_match_fraction", -1.0)) != float(
        settings["minimum_core_match_fraction"]
    ):
        raise ValueError("public CMR census completeness threshold changed")
    exact_zeroes = {
        "credentials_used": False,
        "data_object_urls_followed": 0,
        "thermal_or_science_values_opened": 0,
        "holdout_included": False,
        "record_2026_included": False,
    }
    for field, expected in exact_zeroes.items():
        if record.get(field) != expected:
            raise ValueError(f"public CMR census violated prethermal field {field}")
    summaries = record.get("product_summaries")
    if not isinstance(summaries, list):
        raise ValueError("public CMR census has no product summaries")
    by_family = {
        str(item.get("family")): item for item in summaries if isinstance(item, Mapping)
    }
    products = _cmr_products(config)
    if set(by_family) != {str(item["family"]) for item in products}:
        raise ValueError("public CMR census product set changed")
    threshold = float(settings["minimum_core_match_fraction"])
    for product in products:
        summary = by_family[str(product["family"])]
        if bool(summary.get("core_product")) != bool(product["core"]):
            raise ValueError(f"{product['family']}: CMR census core role changed")
        if bool(product["core"]) and float(summary.get("match_fraction", -1.0)) < threshold:
            raise ValueError(f"{product['family']}: core match completeness is below threshold")
        if expected_associations is not None and int(
            summary.get("expected_associations", -1)
        ) != int(expected_associations):
            raise ValueError(f"{product['family']}: expected association count changed")
    if record.get("et_alexi_role") not in {
        "AVAILABLE_SECONDARY_SENSITIVITY_ONLY_NOT_CORE",
        "DEMOTED_AVAILABILITY_LIMITED_OPTIONAL_STEP5_NOT_CORE",
    }:
        raise ValueError("ET_ALEXI role is not availability-gated and non-core")
    for rel, expected_hash in record.get("artifact_hashes", {}).items():
        if sha256_file(_repo_path(root, rel)) != expected_hash:
            raise ValueError(f"public CMR census artifact hash changed: {rel}")
    return record_path, record


def _require_task1_time_of_day_pass(
    config: Mapping[str, Any], *, root: Path
) -> tuple[Path, dict[str, Any]]:
    gate_path = _repo_path(root, config["task2"]["canonical_task1_gate"])
    gate = _read_json(gate_path)
    if gate is None:
        step3_path = _repo_path(root, config["evidence"]["time_of_day_step3_gate"])
        step3 = _read_json(step3_path)
        if step3 is not None and str(step3.get("status", "")).startswith("STOP"):
            raise ValueError(
                "upstream D0056 Step3 STOP prevents Task2A: "
                f"status={step3.get('status')}; failed={step3.get('failed_check_ids', [])}"
            )
        raise ValueError(f"scoped Task1 time-of-day PASS gate is missing: {gate_path}")
    exact = {
        "task1_gate": EXPECTED_GATE,
        "profile_gate": EXPECTED_PROFILE_GATE,
        "analysis_profile": EXPECTED_PROFILE,
        "scientific_gate_scope": EXPECTED_SCOPE,
        **REQUIRED_LOCO_GATE_FIELDS,
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            raise ValueError(
                f"scoped Task1 time-of-day gate {field} changed: "
                f"expected={expected!r}; found={gate.get(field)!r}"
            )
    _validate_gate_with_branch_validator(gate, gate_path, root)
    return gate_path, gate


def build_prethermal_evidence(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Build the Task-2A freeze evidence from nonthermal metadata only."""

    root = Path(repo_root).expanduser().resolve()
    config_path = Path(config_path).expanduser().resolve()
    config = load_config(config_path)
    task1_gate_path, _ = _require_task1_time_of_day_pass(config, root=root)
    evidence = config["evidence"]
    counts_path = _repo_path(root, evidence["pass_counts"])
    catalogue_path = _repo_path(root, evidence["scene_catalogue"])
    stop_path = _repo_path(root, evidence["interaction_stop_gate"])
    output_root = _repo_path(root, evidence["output_root"])
    freeze_path = _repo_path(root, evidence["freeze_record"])

    with stop_path.open("r", encoding="utf-8") as handle:
        stop_gate = json.load(handle)
    if stop_gate.get("status") != "STOP" or stop_gate.get("count_support_pass") is not False:
        raise ValueError("D0057 must preserve the interaction count-support STOP")
    if stop_gate.get("lst_opened") is not False or stop_gate.get("thermal_opened") is not False:
        raise ValueError("interaction gate does not prove a prethermal boundary")

    counts = pd.read_csv(counts_path)
    ranking = _holdout_ranking(config, counts)
    catalogue = pd.read_csv(catalogue_path, low_memory=False)
    scene_facts = _scene_inventory(config, catalogue)
    cmr_record_path, cmr_record = _validated_public_cmr_census(
        config,
        config_path=config_path,
        root=root,
        expected_associations=scene_facts["development_pass_tile_associations"],
    )
    products, storage, storage_summary = _product_and_storage_tables(config, scene_facts)
    availability = {
        str(item["family"]): item for item in cmr_record["product_summaries"]
    }
    products["cmr_exact_match_fraction"] = products["family"].map(
        lambda family: availability.get(str(family), {}).get("match_fraction")
    )
    products["cmr_availability_role"] = products["family"].map(
        lambda family: (
            cmr_record["et_alexi_role"]
            if family == "ET_ALEXI"
            else "CORE_CENSUS_PASS"
            if family in availability
            else "SEPARATE_HLS_METADATA_GATE"
        )
    )

    output_root.mkdir(parents=True, exist_ok=True)
    ranking_path = output_root / "holdout_quality_ranking.csv"
    products_path = output_root / "product_chain_inventory.csv"
    storage_path = output_root / "storage_projection.csv"
    _write_csv(ranking, ranking_path)
    _write_csv(products, products_path)
    _write_csv(storage, storage_path)

    free_bytes = shutil.disk_usage(root).free
    required_free = int(storage_summary["required_free_bytes"])
    record: dict[str, Any] = {
        "schema_version": 1,
        "decision_id": config["task2"]["decision_id"],
        "analysis_profile": config["task2"]["analysis_profile"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "FROZEN_PRETHERMAL_READY" if free_bytes >= required_free else "STOP_STORAGE",
        "primary_objective": config["scope"]["primary_objective"],
        "primary_endpoint": config["scope"]["primary_endpoint"],
        "prohibited_claims": list(config["scope"]["prohibited_claims"]),
        "holdout_status": config["task2"]["holdout_status"],
        "holdout_city": config["task2"]["holdout_city"],
        "holdout_selection_basis": config["holdout"]["selection_basis"],
        "development_cities": list(config["task2"]["development_cities"]),
        "scene_facts": scene_facts,
        "time_strata": dict(config["time_strata"]),
        "collection_version": config["collection"]["primary_collection_version"],
        "primary_products": products.loc[products["primary_chain"], "product"].tolist(),
        "public_cmr_core_product_status": cmr_record["status"],
        "public_cmr_product_summaries": cmr_record["product_summaries"],
        "et_alexi_role": cmr_record["et_alexi_role"],
        "storage": {
            **storage_summary,
            "free_bytes_at_freeze": int(free_bytes),
            "headroom_pass_at_freeze": bool(free_bytes >= required_free),
            "recheck_before_each_batch": bool(config["storage"]["recheck_before_each_batch"]),
        },
        "source_hashes": {
            str(task1_gate_path.relative_to(root)): sha256_file(task1_gate_path),
            evidence["pass_counts"]: sha256_file(counts_path),
            evidence["scene_catalogue"]: sha256_file(catalogue_path),
            evidence["interaction_stop_gate"]: sha256_file(stop_path),
            str(cmr_record_path.relative_to(root)): sha256_file(cmr_record_path),
        },
        "artifact_hashes": {
            str(ranking_path.relative_to(root)): sha256_file(ranking_path),
            str(products_path.relative_to(root)): sha256_file(products_path),
            str(storage_path.relative_to(root)): sha256_file(storage_path),
        },
        "configuration_path": str(config_path.relative_to(root)),
        "configuration_sha256": sha256_file(config_path),
        "interaction_stop_preserved": True,
        "lst_or_thermal_layers_opened": 0,
        "holdout_thermal_opened": False,
        "record_2026_opened": False,
    }
    freeze_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _block(blockers: list[Blocker], code: str, detail: str) -> None:
    blockers.append(Blocker(code=code, detail=detail))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _validate_gate_with_branch_validator(gate: Mapping[str, Any], gate_path: Path, root: Path) -> None:
    from urban_cooling_v2.task1_time_of_day_gate import validate_time_of_day_task1_pass

    validate_time_of_day_task1_pass(gate, gate_path=str(gate_path), repo_root=root)


def run_preflight(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    repo_root: str | Path = REPO_ROOT,
) -> PreflightReport:
    """Evaluate the exact D0056/D0057 contract without raster or network access."""

    root = Path(repo_root).expanduser().resolve()
    config_path = Path(config_path).expanduser().resolve()
    config = load_config(config_path)
    blockers: list[Blocker] = []
    task2 = config.get("task2", {})
    scope = config.get("scope", {})
    decisions = config.get("decisions", {})
    collection = config.get("collection", {})
    storage_config = config.get("storage", {})
    evidence = config.get("evidence", {})

    try:
        gate_path = _repo_path(root, str(task2.get("canonical_task1_gate", "")))
    except ValueError as exc:
        gate_path = root / "__INVALID_TIME_OF_DAY_GATE__"
        _block(blockers, "TASK1_GATE_PATH_INVALID", str(exc))
    try:
        gate = _read_json(gate_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        gate = None
        _block(blockers, "TASK1_GATE_UNREADABLE", str(exc))
    gate_value = "MISSING" if gate is None else str(gate.get("task1_gate", "MISSING"))
    if gate is None:
        _block(blockers, "TASK1_TIME_OF_DAY_GATE_MISSING", str(gate_path))
        try:
            step3_path = _repo_path(root, str(evidence.get("time_of_day_step3_gate", "")))
            step3 = _read_json(step3_path)
        except (OSError, ValueError, json.JSONDecodeError):
            step3 = None
        if step3 is not None and str(step3.get("status", "")).startswith("STOP"):
            _block(
                blockers,
                "UPSTREAM_TIME_OF_DAY_STEP3_STOP",
                f"status={step3.get('status')}; failed={step3.get('failed_check_ids', [])}",
            )
    else:
        exact = {
            "task1_gate": EXPECTED_GATE,
            "profile_gate": EXPECTED_PROFILE_GATE,
            "analysis_profile": EXPECTED_PROFILE,
            "scientific_gate_scope": EXPECTED_SCOPE,
            **REQUIRED_LOCO_GATE_FIELDS,
        }
        for key, expected in exact.items():
            if gate.get(key) != expected:
                _block(
                    blockers,
                    f"TASK1_{key.upper()}_MISMATCH",
                    f"expected {expected!r}, found {gate.get(key)!r}",
                )
        try:
            _validate_gate_with_branch_validator(gate, gate_path, root)
        except (ImportError, OSError, ValueError, TypeError) as exc:
            _block(blockers, "TASK1_TIME_OF_DAY_GATE_INVALID", str(exc))

    if task2.get("analysis_profile") != EXPECTED_PROFILE:
        _block(blockers, "ANALYSIS_PROFILE_MISMATCH", "D0056 branch profile is required")
    if tuple(task2.get("development_cities", ())) != EXPECTED_DEVELOPMENT_CITIES:
        _block(blockers, "DEVELOPMENT_CITY_SET_MISMATCH", "four frozen development cities required")
    if task2.get("holdout_status") != "SELECTED_QUALITY_ONLY" or task2.get(
        "holdout_city"
    ) != EXPECTED_HOLDOUT:
        _block(blockers, "HOLDOUT_NOT_FROZEN", "quality-only Minneapolis holdout is required")
    if task2.get("heldout_thermal_status") != "UNOPENED":
        _block(blockers, "HOLDOUT_THERMAL_NOT_LOCKED", "holdout thermal must be UNOPENED")
    if task2.get("season_2026_status") != "UNOPENED":
        _block(blockers, "SEASON_2026_NOT_LOCKED", "2026 must remain UNOPENED")
    if task2.get("result_bearing_actions_enabled") is not True:
        _block(blockers, "RESULT_ACTIONS_DISABLED", "explicit D0056 coordinator enable is required")
    if scope.get("primary_objective") != "time_of_day_dependence":
        _block(blockers, "PRIMARY_OBJECTIVE_INVALID", "time-of-day dependence must be sole primary")
    required_prohibitions = {
        "demand_by_antecedent_dryness_interaction",
        "demand_by_antecedent_dryness_by_time_interaction",
        "hydroclimatic_transition_threshold",
    }
    if not required_prohibitions.issubset(set(scope.get("prohibited_claims", ()))):
        _block(blockers, "PROHIBITED_CLAIMS_INCOMPLETE", "interaction/transition claims must stay blocked")

    for key in FROZEN_DECISIONS:
        if decisions.get(key) != "FROZEN":
            _block(blockers, f"DECISION_{key.upper()}", f"{key} must be FROZEN")
    if decisions.get("supporting_product_chain_status") != (
        "FROZEN_TO_PUBLIC_CMR_CENSUS_GATE"
    ):
        _block(
            blockers,
            "DECISION_SUPPORTING_PRODUCT_CHAIN_STATUS",
            "supporting-product policy must be frozen to the public-CMR census gate",
        )
    if collection.get("primary_collection_version") != "002":
        _block(blockers, "PRIMARY_COLLECTION_NOT_002", "complete Collection-2 chain is frozen")
    if collection.get("mix_primary_collection_versions") is not False:
        _block(blockers, "PRIMARY_COLLECTION_MIX_ENABLED", "primary versions may not mix")
    if collection.get("temperature_resampling") is not False:
        _block(blockers, "TEMPERATURE_RESAMPLING_ENABLED", "temperature must remain native")

    try:
        _validated_public_cmr_census(
            config,
            config_path=config_path,
            root=root,
            expected_associations=719,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _block(blockers, "PUBLIC_CMR_CENSUS_INVALID", str(exc))

    projected = int(storage_config.get("projected_peak_bytes", 0))
    multiplier = float(storage_config.get("headroom_multiplier", 0.0))
    reserve = int(storage_config.get("minimum_reserve_bytes", 0))
    required_free = int(projected * multiplier) + reserve
    free_bytes = shutil.disk_usage(root).free
    if projected <= 0 or storage_config.get("status") != "FROZEN":
        _block(blockers, "STORAGE_NOT_FROZEN", "positive frozen metadata-only projection required")
    elif free_bytes < required_free:
        _block(
            blockers,
            "INSUFFICIENT_STORAGE_HEADROOM",
            f"free={free_bytes}; required={required_free}",
        )
    if storage_config.get("delete_existing_data") is not False:
        _block(blockers, "DESTRUCTIVE_STORAGE_PLAN", "existing data may not be deleted")
    if storage_config.get("persist_signed_urls") is not False:
        _block(blockers, "SIGNED_URL_PERSISTENCE", "signed URLs may not be persisted")
    if storage_config.get("preserve_native_temperature_grid") is not True:
        _block(blockers, "NATIVE_GRID_NOT_FROZEN", "native temperature grid must be retained")

    try:
        freeze_path = _repo_path(root, str(evidence.get("freeze_record", "")))
        freeze = _read_json(freeze_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        freeze_path = root / "__INVALID_TASK2A_FREEZE__"
        freeze = None
        _block(blockers, "TASK2A_FREEZE_UNREADABLE", str(exc))
    if freeze is None:
        _block(blockers, "TASK2A_FREEZE_MISSING", str(freeze_path))
    else:
        if freeze.get("decision_id") != task2.get("decision_id"):
            _block(blockers, "TASK2A_DECISION_MISMATCH", "freeze record is not bound to D0057")
        if freeze.get("holdout_city") != EXPECTED_HOLDOUT:
            _block(blockers, "TASK2A_HOLDOUT_MISMATCH", "freeze record holdout changed")
        if freeze.get("interaction_stop_preserved") is not True:
            _block(blockers, "INTERACTION_STOP_NOT_PRESERVED", "R0015 STOP must remain immutable")
        if freeze.get("lst_or_thermal_layers_opened") != 0:
            _block(blockers, "THERMAL_ALREADY_OPENED", "Task2A evidence must be prethermal")
        if freeze.get("holdout_thermal_opened") is not False:
            _block(blockers, "HOLDOUT_ALREADY_OPENED", "holdout thermal was not locked")
        if freeze.get("record_2026_opened") is not False:
            _block(blockers, "RECORD_2026_ALREADY_OPENED", "2026 was not locked")
        if freeze.get("public_cmr_core_product_status") != (
            "PASS_CORE_PRODUCT_AVAILABILITY"
        ):
            _block(
                blockers,
                "TASK2A_CORE_PRODUCT_AVAILABILITY_NOT_PASSED",
                "LSTE/STARS/SEB/JET/ESI public-CMR availability must pass",
            )
        if freeze.get("et_alexi_role") not in {
            "AVAILABLE_SECONDARY_SENSITIVITY_ONLY_NOT_CORE",
            "DEMOTED_AVAILABILITY_LIMITED_OPTIONAL_STEP5_NOT_CORE",
        }:
            _block(
                blockers,
                "TASK2A_ET_ALEXI_ROLE_INVALID",
                "ET_ALEXI must stay a non-core Step-5 availability-gated sensitivity",
            )
        if freeze.get("configuration_sha256") != sha256_file(config_path):
            _block(blockers, "TASK2A_CONFIG_HASH_MISMATCH", "configuration changed after freeze")
        for rel, expected_hash in freeze.get("source_hashes", {}).items():
            try:
                actual = sha256_file(_repo_path(root, rel))
            except (OSError, ValueError) as exc:
                _block(blockers, "TASK2A_SOURCE_UNREADABLE", f"{rel}: {exc}")
                continue
            if actual != expected_hash:
                _block(blockers, "TASK2A_SOURCE_HASH_MISMATCH", rel)
        for rel, expected_hash in freeze.get("artifact_hashes", {}).items():
            try:
                actual = sha256_file(_repo_path(root, rel))
            except (OSError, ValueError) as exc:
                _block(blockers, "TASK2A_ARTIFACT_UNREADABLE", f"{rel}: {exc}")
                continue
            if actual != expected_hash:
                _block(blockers, "TASK2A_ARTIFACT_HASH_MISMATCH", rel)

    decision_log = root / "docs" / "v2" / "DECISION_LOG.md"
    if decision_log.is_file() and "| D0057 |" not in decision_log.read_text(encoding="utf-8"):
        _block(blockers, "D0057_DECISION_NOT_LOGGED", "append-only D0057 row is required")

    return PreflightReport(
        ready=not blockers,
        blockers=tuple(blockers),
        task1_gate_path=str(gate_path),
        task1_gate_value=gate_value,
        holdout_city=str(task2.get("holdout_city", "")),
        development_cities=tuple(task2.get("development_cities", ())),
        free_bytes=int(free_bytes),
        projected_peak_bytes=projected,
        required_free_bytes=required_free,
    )
