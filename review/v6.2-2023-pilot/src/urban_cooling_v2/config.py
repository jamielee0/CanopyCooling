"""Typed loader and invariants for the frozen v2 feasibility configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "v2_cities.toml"


@dataclass(frozen=True)
class CityConfig:
    slug: str
    label: str
    urban_area_geoid: str
    urban_area_name: str
    area_land_km2: float
    centroid_lat: float
    centroid_lon: float
    climate_role: str


@dataclass(frozen=True)
class StudyConfig:
    study: dict[str, Any]
    weather: dict[str, Any]
    ecostress: dict[str, Any]
    simulation: dict[str, Any]
    cities: tuple[CityConfig, ...]
    source_path: Path

    @property
    def city_slugs(self) -> tuple[str, ...]:
        return tuple(city.slug for city in self.cities)

    def city(self, slug: str) -> CityConfig:
        for city in self.cities:
            if city.slug == slug:
                return city
        raise KeyError(f"unknown city slug: {slug!r}")


def _validate(raw: dict[str, Any], path: Path) -> None:
    required = {"study", "weather", "ecostress", "simulation", "cities"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing top-level sections {sorted(missing)}")
    cities = raw["cities"]
    if len(cities) != 5:
        raise ValueError(f"{path}: exactly five cities are required, got {len(cities)}")
    for field in ("slug", "label", "urban_area_geoid", "urban_area_name"):
        values = [str(city.get(field, "")) for city in cities]
        if any(not value for value in values):
            raise ValueError(f"{path}: every city requires non-empty {field}")
        if len(values) != len(set(values)):
            raise ValueError(f"{path}: city {field} values must be unique")
    if raw["study"].get("holdout_status") != "UNSELECTED":
        holdout = raw["study"].get("holdout_city", "")
        if holdout not in {city["slug"] for city in cities}:
            raise ValueError("a selected holdout_city must be one of the five frozen cities")
    if raw["study"].get("holdout_status") == "UNSELECTED" and raw["study"].get("holdout_city"):
        raise ValueError("holdout_city must be blank while holdout_status is UNSELECTED")
    if str(raw["ecostress"].get("catalogue_version", "")) not in {"002", "003"}:
        raise ValueError("ECOSTRESS catalogue_version must be a three-digit version")
    edges = [float(x) for x in raw["ecostress"].get("time_strata_hours", [])]
    if edges != sorted(set(edges)) or len(edges) != 5:
        raise ValueError("time_strata_hours must contain five unique increasing edges")


def load_config(path: str | Path = DEFAULT_CONFIG) -> StudyConfig:
    """Load the frozen TOML configuration and enforce cross-field invariants."""
    source = Path(path).expanduser().resolve()
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    _validate(raw, source)
    cities = tuple(CityConfig(**item) for item in raw["cities"])
    return StudyConfig(
        study=dict(raw["study"]),
        weather=dict(raw["weather"]),
        ecostress=dict(raw["ecostress"]),
        simulation=dict(raw["simulation"]),
        cities=cities,
        source_path=source,
    )
