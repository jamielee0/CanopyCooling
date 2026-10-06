#!/usr/bin/env python3
"""Official ECOSTRESS metadata enrichment for the Step-2 feasibility audit.

The CMR catalogue establishes that a tiled granule exists, but several Step-2
screening fields live in official per-granule sidecars instead:

* L2T JSON: ``FieldOfViewObstruction``, ``AutomaticQualityFlag``,
  ``NumberOfBands``, and ``QAPercentCloudCover``;
* L1B GEO DMR++/XML: ``GeolocationAccuracyQA``;
* the published ``obst_all_sort.txt`` list: obstructed orbit/scene pairs.

This module parses those sources without downloading LST.  It also summarizes
local view-zenith and cloud arrays inside a frozen domain mask.  Unknown fields
are never promoted to usable: missing geolocation becomes ``suspect`` and
missing obstruction evidence is conservatively excluded.

All parsers are pure apart from optional local-file reads.  The checkpoint
helpers store only caller-provided item IDs and local file evidence; they do not
accept or persist URLs, authorization headers, tokens, or passwords.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import base64
import hashlib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


QUALITY_ORDER = ("best", "good", "suspect", "poor")
QUALITY_RANK = {quality: rank for rank, quality in enumerate(QUALITY_ORDER)}
USABLE_GEOLOCATION_QUALITY = frozenset(("best", "good"))


class MetadataParseError(ValueError):
    """Raised when an official sidecar cannot be interpreted safely."""


@dataclasses.dataclass(frozen=True, order=True)
class SceneKey:
    """An ECOSTRESS pass key shared by tiled L2T and swath L1B products."""

    orbit: int
    scene: int

    def __post_init__(self) -> None:
        if self.orbit <= 0:
            raise ValueError("Orbit must be a positive integer")
        if not 0 <= self.scene <= 999:
            raise ValueError("Scene must be between 0 and 999")

    @property
    def label(self) -> str:
        return f"{self.orbit:05d}_{self.scene:03d}"


@dataclasses.dataclass(frozen=True)
class L2TGranuleMetadata:
    source_name: str
    granule_id: str
    key: SceneKey
    field_of_view_obstruction: bool | None
    automatic_quality_flag: str
    number_of_bands: int | None
    qa_percent_cloud_cover: float | None
    raw_field_of_view_obstruction: str | None = None
    raw_automatic_quality_flag: str | None = None
    warnings: tuple[str, ...] = ()

    def as_row(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "granule_id": self.granule_id,
            "orbit": self.key.orbit,
            "scene": self.key.scene,
            "field_of_view_obstruction": self.field_of_view_obstruction,
            "automatic_quality_flag": self.automatic_quality_flag,
            "number_of_bands": self.number_of_bands,
            "qa_percent_cloud_cover": self.qa_percent_cloud_cover,
            "raw_field_of_view_obstruction": self.raw_field_of_view_obstruction,
            "raw_automatic_quality_flag": self.raw_automatic_quality_flag,
            "metadata_warnings": " | ".join(self.warnings),
        }


@dataclasses.dataclass(frozen=True)
class GeoAccuracyMetadata:
    source_name: str
    key: SceneKey
    geolocation_quality: str
    raw_geolocation_accuracy_qa: str | None
    warnings: tuple[str, ...] = ()

    def as_row(self) -> dict[str, Any]:
        return {
            "geo_source_name": self.source_name,
            "orbit": self.key.orbit,
            "scene": self.key.scene,
            "geolocation_quality": self.geolocation_quality,
            "raw_geolocation_accuracy_qa": self.raw_geolocation_accuracy_qa,
            "geo_metadata_warnings": " | ".join(self.warnings),
        }


@dataclasses.dataclass(frozen=True)
class ObstructionListResult:
    entries: tuple[SceneKey, ...]
    unparsed_lines: tuple[tuple[int, str], ...] = ()

    def as_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "orbit": entry.orbit,
                    "scene": entry.scene,
                    "published_obstruction_flag": True,
                }
                for entry in self.entries
            ],
            columns=("orbit", "scene", "published_obstruction_flag"),
        )


def _normalized_name(value: Any) -> str:
    text = str(value)
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _read_text_source(
    source: str | bytes | os.PathLike[str],
    *,
    expected_opening: str,
) -> tuple[str, str]:
    if isinstance(source, bytes):
        return source.decode("utf-8-sig"), "<bytes>"
    if isinstance(source, os.PathLike):
        path = Path(source)
        return path.read_text(encoding="utf-8-sig"), path.name
    text = str(source)
    if text.lstrip().startswith(expected_opening):
        return text, "<memory>"
    path = Path(text)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8-sig"), path.name


def _unwrap_scalars(value: Any) -> list[Any]:
    """Flatten common UMM/HDF wrappers while preserving scalar evidence."""

    if value is None:
        return []
    if isinstance(value, Mapping):
        wrapper_names = {
            "value",
            "values",
            "text",
            "content",
            "data",
            "#text",
        }
        for key, nested in value.items():
            if _normalized_name(key) in {_normalized_name(name) for name in wrapper_names}:
                extracted = _unwrap_scalars(nested)
                if extracted:
                    return extracted
        if len(value) == 1:
            return _unwrap_scalars(next(iter(value.values())))
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[Any] = []
        for item in value:
            result.extend(_unwrap_scalars(item))
        return result
    return [value]


def _json_field_values(document: Any, aliases: Iterable[str]) -> list[Any]:
    targets = {_normalized_name(alias) for alias in aliases}
    values: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if _normalized_name(key) in targets:
                    values.extend(_unwrap_scalars(value))
                walk(value)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for value in node:
                walk(value)

    walk(document)
    return values


_PRODUCT_KEY_RE = re.compile(
    r"ECOv\d+_L[0-9A-Z]+_[A-Z0-9]+_(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})(?:_|\b)",
    re.IGNORECASE,
)
_GEO_FLAG_LINE_RE = re.compile(
    r"(?P<name>ECOv\d+_L1B_GEO_(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})_"
    r"(?P<timestamp>\d{8}T\d{6})_(?P<build>\d+)_(?P<revision>\d+)(?:\.h5)?)"
    r".*?GeolocationAccuracyQA\s*=\s*[\"'](?P<quality>[^\"']+)[\"']",
    re.IGNORECASE,
)


def scene_key_from_name(value: str) -> SceneKey | None:
    """Extract orbit/scene from an official ECOSTRESS L2T or L1B name."""

    match = _PRODUCT_KEY_RE.search(Path(value).name)
    if not match:
        return None
    return SceneKey(int(match.group("orbit")), int(match.group("scene")))


def _parse_integer(values: Sequence[Any], field: str) -> tuple[int | None, list[str]]:
    parsed: list[int] = []
    warnings: list[str] = []
    for value in values:
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            warnings.append(f"{field}: ignored non-numeric value {value!r}")
            continue
        if not np.isfinite(numeric) or not numeric.is_integer():
            warnings.append(f"{field}: ignored non-integer value {value!r}")
            continue
        parsed.append(int(numeric))
    if not parsed:
        return None, warnings
    if len(set(parsed)) > 1:
        warnings.append(f"{field}: conflicting values {sorted(set(parsed))}; used minimum")
    return min(parsed), warnings


def _parse_percent(values: Sequence[Any], field: str) -> tuple[float | None, list[str]]:
    parsed: list[float] = []
    warnings: list[str] = []
    for value in values:
        text = str(value).strip().rstrip("%")
        try:
            numeric = float(text)
        except (TypeError, ValueError):
            warnings.append(f"{field}: ignored non-numeric value {value!r}")
            continue
        if not 0 <= numeric <= 100:
            warnings.append(f"{field}: ignored value outside 0-100: {value!r}")
            continue
        parsed.append(numeric)
    if not parsed:
        return None, warnings
    if len(set(parsed)) > 1:
        warnings.append(f"{field}: conflicting values {sorted(set(parsed))}; used maximum")
    return max(parsed), warnings


def normalize_quality(value: Any, *, unknown: str = "suspect") -> str:
    """Normalize official quality text/code to best/good/suspect/poor."""

    if value is None:
        return unknown
    text = str(value).strip().casefold().replace("_", " ").replace("-", " ")
    aliases = {
        "0": "best",
        "best": "best",
        "excellent": "best",
        "pass best": "best",
        "1": "good",
        "good": "good",
        "nominal": "good",
        "passed": "good",
        "pass": "good",
        "2": "suspect",
        "suspect": "suspect",
        "questionable": "suspect",
        "unknown": "suspect",
        "not evaluated": "suspect",
        "3": "poor",
        "poor": "poor",
        "bad": "poor",
        "failed": "poor",
        "fail": "poor",
    }
    return aliases.get(text, unknown)


def _worst_quality(values: Iterable[Any], *, missing: str = "suspect") -> str:
    normalized = [normalize_quality(value, unknown=missing) for value in values]
    if not normalized:
        return missing
    return max(normalized, key=lambda quality: QUALITY_RANK[quality])


def parse_obstruction_value(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return bool(value) if value in (0, 1) else None
    text = str(value).strip().casefold().replace("_", " ").replace("-", " ")
    if text in {"1", "true", "yes", "y", "obstructed", "flagged", "present"}:
        return True
    if text in {
        "0",
        "false",
        "no",
        "n",
        "none",
        "clear",
        "not obstructed",
        "unobstructed",
        "absent",
    }:
        return False
    return None


def _coalesce_obstruction(values: Sequence[Any]) -> tuple[bool | None, list[str]]:
    parsed = [parse_obstruction_value(value) for value in values]
    known = [value for value in parsed if value is not None]
    warnings: list[str] = []
    if any(value is None for value in parsed):
        warnings.append("FieldOfViewObstruction contains unrecognized value(s)")
    if not known:
        return None, warnings
    if True in known and False in known:
        warnings.append("FieldOfViewObstruction conflicts across metadata; used obstructed")
    return any(known), warnings


def _first_text(values: Sequence[Any]) -> str | None:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return None


def _scene_key_from_fields(document: Any, fallback_names: Iterable[str]) -> SceneKey | None:
    orbit_values = _json_field_values(document, ("OrbitNumber", "Orbit", "OrbitID"))
    scene_values = _json_field_values(document, ("SceneNumber", "SceneID", "Scene"))
    orbit, _ = _parse_integer(orbit_values, "orbit")
    scene, _ = _parse_integer(scene_values, "scene")
    if orbit is not None and scene is not None:
        return SceneKey(orbit, scene)
    for name in fallback_names:
        key = scene_key_from_name(name)
        if key is not None:
            return key
    return None


def parse_l2t_json(
    source: Mapping[str, Any] | str | bytes | os.PathLike[str],
    *,
    source_name: str | None = None,
) -> L2TGranuleMetadata:
    """Parse one official ECOSTRESS L2T per-granule JSON sidecar."""

    if isinstance(source, Mapping):
        document: Any = source
        detected_name = source_name or "<mapping>"
    else:
        text, detected_name = _read_text_source(source, expected_opening="{")
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MetadataParseError(f"Invalid L2T JSON: {exc}") from exc
        detected_name = source_name or detected_name

    granule_values = _json_field_values(
        document,
        (
            "GranuleUR",
            "LocalGranuleID",
            "ProducerGranuleId",
            "ProducerGranuleID",
            "FileName",
            "GranuleID",
        ),
    )
    granule_id = _first_text(granule_values) or detected_name
    key = _scene_key_from_fields(document, (granule_id, detected_name))
    if key is None:
        raise MetadataParseError(
            f"{detected_name}: could not determine orbit/scene from fields or product name"
        )

    warnings: list[str] = []
    obstruction_values = _json_field_values(document, ("FieldOfViewObstruction",))
    obstruction, field_warnings = _coalesce_obstruction(obstruction_values)
    warnings.extend(field_warnings)
    raw_obstruction = _first_text(obstruction_values)
    if not obstruction_values:
        warnings.append("FieldOfViewObstruction missing")

    quality_values = _json_field_values(document, ("AutomaticQualityFlag",))
    quality = _worst_quality(quality_values)
    raw_quality = _first_text(quality_values)
    if not quality_values:
        warnings.append("AutomaticQualityFlag missing; classified suspect")
    elif any(normalize_quality(value) == "suspect" for value in quality_values):
        recognized_suspect = {
            "2",
            "suspect",
            "questionable",
            "unknown",
            "not evaluated",
        }
        if any(str(value).strip().casefold() not in recognized_suspect for value in quality_values):
            warnings.append("AutomaticQualityFlag contains unrecognized value; classified suspect")

    band_values = _json_field_values(document, ("NumberOfBands",))
    number_of_bands, field_warnings = _parse_integer(band_values, "NumberOfBands")
    warnings.extend(field_warnings)
    if number_of_bands is None:
        warnings.append("NumberOfBands missing or invalid")

    cloud_values = _json_field_values(document, ("QAPercentCloudCover",))
    cloud_cover, field_warnings = _parse_percent(
        cloud_values, "QAPercentCloudCover"
    )
    warnings.extend(field_warnings)
    if cloud_cover is None:
        warnings.append("QAPercentCloudCover missing or invalid")

    return L2TGranuleMetadata(
        source_name=detected_name,
        granule_id=granule_id,
        key=key,
        field_of_view_obstruction=obstruction,
        automatic_quality_flag=quality,
        number_of_bands=number_of_bands,
        qa_percent_cloud_cover=cloud_cover,
        raw_field_of_view_obstruction=raw_obstruction,
        raw_automatic_quality_flag=raw_quality,
        warnings=tuple(warnings),
    )


def _xml_local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _xml_element_values(element: ET.Element) -> list[str]:
    values: list[str] = []
    for attribute_name, attribute_value in element.attrib.items():
        if _normalized_name(attribute_name) in {"value", "values"}:
            text = str(attribute_value).strip()
            if text:
                values.append(text)
    for descendant in element.iter():
        if descendant is element:
            continue
        if _normalized_name(_xml_local_name(descendant.tag)) in {"value", "values"}:
            for attribute_name, attribute_value in descendant.attrib.items():
                if _normalized_name(attribute_name) in {"value", "values"}:
                    text = str(attribute_value).strip()
                    if text:
                        values.append(text)
            if descendant.text and descendant.text.strip():
                values.append(descendant.text.strip())
        elif _normalized_name(_xml_local_name(descendant.tag)) == "compact":
            encoded = descendant.text.strip() if descendant.text else ""
            if encoded:
                try:
                    decoded = base64.b64decode(encoded, validate=True).decode(
                        "utf-8"
                    ).rstrip("\x00")
                except (ValueError, UnicodeDecodeError):
                    continue
                if decoded:
                    values.append(decoded)
    if not values and element.text and element.text.strip():
        values.append(element.text.strip())
    return values


def _xml_field_values(root: ET.Element, aliases: Iterable[str]) -> list[str]:
    targets = {_normalized_name(alias) for alias in aliases}
    values: list[str] = []
    for element in root.iter():
        tag_match = _normalized_name(_xml_local_name(element.tag)) in targets
        named_match = any(
            _normalized_name(attribute_name) in {"name", "id"}
            and _normalized_name(attribute_value) in targets
            for attribute_name, attribute_value in element.attrib.items()
        )
        if tag_match or named_match:
            values.extend(_xml_element_values(element))
    # Preserve order while removing repeated DMR++ renderings of one value.
    return list(dict.fromkeys(values))


def parse_l1b_geo_xml(
    source: str | bytes | os.PathLike[str],
    *,
    source_name: str | None = None,
) -> GeoAccuracyMetadata:
    """Parse ``GeolocationAccuracyQA`` from L1B GEO XML or DMR++ XML."""

    text, detected_name = _read_text_source(source, expected_opening="<")
    detected_name = source_name or detected_name
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise MetadataParseError(f"Invalid L1B GEO XML/DMR++: {exc}") from exc

    key = scene_key_from_name(detected_name)
    if key is None:
        orbit_values = _xml_field_values(root, ("OrbitNumber", "Orbit", "OrbitID"))
        scene_values = _xml_field_values(root, ("SceneNumber", "SceneID", "Scene"))
        orbit, _ = _parse_integer(orbit_values, "orbit")
        scene, _ = _parse_integer(scene_values, "scene")
        if orbit is not None and scene is not None:
            key = SceneKey(orbit, scene)
    if key is None:
        raise MetadataParseError(
            f"{detected_name}: could not determine orbit/scene from XML or product name"
        )

    values = _xml_field_values(root, ("GeolocationAccuracyQA",))
    raw = _first_text(values)
    warnings: list[str] = []
    if not values:
        quality = "suspect"
        warnings.append("GeolocationAccuracyQA missing; classified suspect")
    else:
        quality = _worst_quality(values)
        normalized_unique = {normalize_quality(value) for value in values}
        if len(normalized_unique) > 1:
            warnings.append(
                f"Conflicting GeolocationAccuracyQA values {values}; used worst"
            )
        known_raw = {
            "0",
            "1",
            "2",
            "3",
            "best",
            "excellent",
            "good",
            "nominal",
            "suspect",
            "questionable",
            "unknown",
            "not evaluated",
            "poor",
            "bad",
            "failed",
            "fail",
            "passed",
            "pass",
        }
        if any(str(value).strip().casefold() not in known_raw for value in values):
            warnings.append("Unrecognized GeolocationAccuracyQA value classified suspect")
    return GeoAccuracyMetadata(
        source_name=detected_name,
        key=key,
        geolocation_quality=quality,
        raw_geolocation_accuracy_qa=raw,
        warnings=tuple(warnings),
    )


def parse_geolocation_flag_table(
    source: str | bytes | os.PathLike[str],
    *,
    strict: bool = True,
) -> tuple[GeoAccuracyMetadata, ...]:
    """Parse JPL's versioned ``SP_Geo_Flags.txt`` scene-quality table.

    If multiple product revisions occur for an orbit/scene, the highest build
    and revision wins deterministically.  The filename and raw value remain in
    the returned record for provenance.
    """

    if isinstance(source, os.PathLike):
        text = Path(source).read_text(encoding="utf-8-sig")
    elif isinstance(source, bytes):
        text = source.decode("utf-8-sig")
    else:
        candidate = str(source)
        if "\n" not in candidate and Path(candidate).is_file():
            text = Path(candidate).read_text(encoding="utf-8-sig")
        else:
            text = candidate

    selected: dict[SceneKey, tuple[tuple[int, int, str], GeoAccuracyMetadata]] = {}
    unparsed: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        match = _GEO_FLAG_LINE_RE.search(line)
        if match is None:
            unparsed.append((line_number, raw_line))
            continue
        key = SceneKey(int(match.group("orbit")), int(match.group("scene")))
        raw_quality = match.group("quality").strip()
        quality = normalize_quality(raw_quality)
        recognized = raw_quality.casefold() in {
            "0",
            "1",
            "2",
            "3",
            "best",
            "good",
            "suspect",
            "poor",
        }
        warnings = () if recognized else (
            f"Unrecognized table quality {raw_quality!r}; classified suspect",
        )
        record = GeoAccuracyMetadata(
            source_name=match.group("name"),
            key=key,
            geolocation_quality=quality,
            raw_geolocation_accuracy_qa=raw_quality,
            warnings=warnings,
        )
        rank = (
            int(match.group("build")),
            int(match.group("revision")),
            match.group("timestamp"),
        )
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, record)
    if strict and unparsed:
        preview = "; ".join(
            f"line {number}: {line!r}" for number, line in unparsed[:3]
        )
        raise MetadataParseError(f"Unparsed geolocation-flag record(s): {preview}")
    return tuple(selected[key][1] for key in sorted(selected))


_LABELED_ORBIT_SCENE_RE = re.compile(
    r"(?:orbit|orb)\s*[:=]?\s*(?P<orbit>\d{3,7}).*?"
    r"(?:scene|scn)\s*[:=]?\s*(?P<scene>\d{1,3})",
    re.IGNORECASE,
)
_LABELED_SCENE_ORBIT_RE = re.compile(
    r"(?:scene|scn)\s*[:=]?\s*(?P<scene>\d{1,3}).*?"
    r"(?:orbit|orb)\s*[:=]?\s*(?P<orbit>\d{3,7})",
    re.IGNORECASE,
)
_PLAIN_PAIR_RE = re.compile(
    r"^\s*(?P<orbit>\d{3,7})\s*[,;_|\t ]+\s*(?P<scene>\d{1,3})(?:\s|[,;_|].*|$)"
)


def _scene_key_from_obstruction_line(line: str) -> SceneKey | None:
    product = scene_key_from_name(line)
    if product is not None:
        return product
    for pattern in (_LABELED_ORBIT_SCENE_RE, _LABELED_SCENE_ORBIT_RE, _PLAIN_PAIR_RE):
        match = pattern.search(line)
        if match:
            return SceneKey(int(match.group("orbit")), int(match.group("scene")))
    return None


def parse_obstruction_list(
    source: str | bytes | os.PathLike[str],
    *,
    strict: bool = True,
) -> ObstructionListResult:
    """Parse official ``obst_all_sort.txt`` into unique orbit/scene keys."""

    if isinstance(source, os.PathLike):
        text = Path(source).read_text(encoding="utf-8-sig")
    elif isinstance(source, bytes):
        text = source.decode("utf-8-sig")
    else:
        candidate = str(source)
        # Obstruction-list content normally contains a newline.  A single-line
        # existing path is still supported without treating arbitrary text as a path.
        if "\n" not in candidate and Path(candidate).is_file():
            text = Path(candidate).read_text(encoding="utf-8-sig")
        else:
            text = candidate

    entries: set[SceneKey] = set()
    unparsed: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = re.split(r"\s+#|//", raw_line, maxsplit=1)[0].strip()
        if not line or line.startswith(("#", ";")):
            continue
        normalized = _normalized_name(line)
        if "orbit" in line.casefold() and "scene" in line.casefold() and not re.search(
            r"\d", line
        ):
            continue
        key = _scene_key_from_obstruction_line(line)
        if key is None:
            unparsed.append((line_number, raw_line))
        else:
            entries.add(key)
    if strict and unparsed:
        preview = "; ".join(f"line {number}: {line!r}" for number, line in unparsed[:3])
        raise MetadataParseError(f"Unparsed obstruction-list record(s): {preview}")
    return ObstructionListResult(tuple(sorted(entries)), tuple(unparsed))


def retrieval_band_mode(number_of_bands: int | None) -> str:
    """Convert official NumberOfBands to a transparent categorical mode."""

    if number_of_bands is None:
        return "unknown"
    if number_of_bands >= 5:
        return "full"
    if 0 < number_of_bands <= 3:
        return "reduced"
    return "unknown"


def _as_l2t_record(value: L2TGranuleMetadata | Mapping[str, Any]) -> L2TGranuleMetadata:
    if isinstance(value, L2TGranuleMetadata):
        return value
    key = SceneKey(int(value["orbit"]), int(value["scene"]))
    return L2TGranuleMetadata(
        source_name=str(value.get("source_name", "<mapping>")),
        granule_id=str(value.get("granule_id", "<unknown>")),
        key=key,
        field_of_view_obstruction=value.get("field_of_view_obstruction"),
        automatic_quality_flag=normalize_quality(value.get("automatic_quality_flag")),
        number_of_bands=(
            int(value["number_of_bands"])
            if value.get("number_of_bands") is not None
            and not pd.isna(value.get("number_of_bands"))
            else None
        ),
        qa_percent_cloud_cover=(
            float(value["qa_percent_cloud_cover"])
            if value.get("qa_percent_cloud_cover") is not None
            and not pd.isna(value.get("qa_percent_cloud_cover"))
            else None
        ),
        raw_field_of_view_obstruction=value.get("raw_field_of_view_obstruction"),
        raw_automatic_quality_flag=value.get("raw_automatic_quality_flag"),
        warnings=tuple(value.get("warnings", ())),
    )


def _as_geo_record(value: GeoAccuracyMetadata | Mapping[str, Any]) -> GeoAccuracyMetadata:
    if isinstance(value, GeoAccuracyMetadata):
        return value
    return GeoAccuracyMetadata(
        source_name=str(value.get("source_name", value.get("geo_source_name", "<mapping>"))),
        key=SceneKey(int(value["orbit"]), int(value["scene"])),
        geolocation_quality=normalize_quality(value.get("geolocation_quality")),
        raw_geolocation_accuracy_qa=value.get("raw_geolocation_accuracy_qa"),
        warnings=tuple(value.get("warnings", ())),
    )


def combine_official_scene_metadata(
    l2t_records: Iterable[L2TGranuleMetadata | Mapping[str, Any]],
    geo_records: Iterable[GeoAccuracyMetadata | Mapping[str, Any]],
    obstruction_entries: ObstructionListResult | Iterable[SceneKey],
) -> pd.DataFrame:
    """Combine official metadata to one conservative row per orbit/scene.

    Tile conflicts use the most exclusionary evidence: worst quality, maximum
    cloud cover, minimum band count, and obstruction if any tile/list says yes.
    If every sidecar explicitly says unobstructed the scene is clear; otherwise
    missing obstruction evidence is marked ``unknown_excluded`` and the boolean
    ``obstruction_flag`` remains true for safe downstream filtering.
    """

    l2t = [_as_l2t_record(record) for record in l2t_records]
    geo = [_as_geo_record(record) for record in geo_records]
    if isinstance(obstruction_entries, ObstructionListResult):
        published = set(obstruction_entries.entries)
    else:
        published = set(obstruction_entries)

    geo_by_key: dict[SceneKey, list[GeoAccuracyMetadata]] = {}
    for record in geo:
        geo_by_key.setdefault(record.key, []).append(record)

    rows: list[dict[str, Any]] = []
    l2t_by_key: dict[SceneKey, list[L2TGranuleMetadata]] = {}
    for record in l2t:
        l2t_by_key.setdefault(record.key, []).append(record)
    for key, records in sorted(l2t_by_key.items()):
        # GranuleUR can repeat when the same sidecar was discovered twice.
        unique_by_id = {record.granule_id: record for record in records}
        records = list(unique_by_id.values())
        fov_values = [record.field_of_view_obstruction for record in records]
        published_flag = key in published
        if published_flag or any(value is True for value in fov_values):
            obstruction_status = "flagged"
            obstruction_flag = True
        elif fov_values and all(value is False for value in fov_values):
            obstruction_status = "clear"
            obstruction_flag = False
        else:
            obstruction_status = "unknown_excluded"
            obstruction_flag = True

        geo_matches = geo_by_key.get(key, [])
        geolocation_quality = _worst_quality(
            (record.geolocation_quality for record in geo_matches)
        )
        band_counts = [
            record.number_of_bands
            for record in records
            if record.number_of_bands is not None
        ]
        minimum_band_count = min(band_counts) if band_counts else None
        observed_modes = {retrieval_band_mode(count) for count in band_counts}
        observed_modes.discard("unknown")
        mode = (
            next(iter(observed_modes))
            if len(observed_modes) == 1
            else "mixed"
            if len(observed_modes) > 1
            else "unknown"
        )
        cloud_values = [
            record.qa_percent_cloud_cover
            for record in records
            if record.qa_percent_cloud_cover is not None
        ]
        product_quality = _worst_quality(
            record.automatic_quality_flag for record in records
        )
        warnings = [warning for record in records for warning in record.warnings]
        warnings.extend(warning for record in geo_matches for warning in record.warnings)
        if not geo_matches:
            warnings.append("No matching L1B GEO metadata; geolocation classified suspect")
        if obstruction_status == "unknown_excluded":
            warnings.append("Obstruction evidence incomplete; scene excluded conservatively")
        rows.append(
            {
                "orbit": key.orbit,
                "scene": key.scene,
                "scene_key": key.label,
                "granule_id": "|".join(sorted(unique_by_id)),
                "n_l2t_tiles": len(records),
                "product_quality": product_quality,
                "automatic_quality_flag": product_quality,
                "geolocation_quality": geolocation_quality,
                "geolocation_usable": geolocation_quality
                in USABLE_GEOLOCATION_QUALITY,
                "field_of_view_obstruction_any": (
                    True
                    if any(value is True for value in fov_values)
                    else False
                    if fov_values and all(value is False for value in fov_values)
                    else None
                ),
                "published_obstruction_flag": published_flag,
                "obstruction_status": obstruction_status,
                "obstruction_flag": obstruction_flag,
                "number_of_bands_min": minimum_band_count,
                "retrieval_band_count": minimum_band_count,
                "retrieval_band_mode": mode,
                "reported_band_mode": mode,
                "qa_percent_cloud_cover_max": max(cloud_values)
                if cloud_values
                else np.nan,
                "qa_percent_cloud_cover": max(cloud_values)
                if cloud_values
                else np.nan,
                "l2t_metadata_sources": "|".join(
                    sorted({record.source_name for record in records})
                ),
                "geo_metadata_sources": "|".join(
                    sorted({record.source_name for record in geo_matches})
                ),
                "official_metadata_complete": bool(
                    geo_matches
                    and obstruction_status != "unknown_excluded"
                    and minimum_band_count is not None
                    and cloud_values
                ),
                "metadata_warnings": " | ".join(dict.fromkeys(warnings)),
            }
        )
    return pd.DataFrame(rows)


def _coerce_key_columns(catalogue: pd.DataFrame) -> pd.DataFrame:
    out = catalogue.copy()
    if "orbit" not in out:
        raise ValueError("Catalogue needs an orbit column")
    out["orbit"] = pd.to_numeric(out["orbit"], errors="coerce")
    if "scene" not in out:
        if "granule_id" not in out:
            raise ValueError("Catalogue needs scene or parseable granule_id")
        parsed = out["granule_id"].astype(str).map(scene_key_from_name)
        out["scene"] = parsed.map(lambda key: key.scene if key else np.nan)
        parsed_orbit = parsed.map(lambda key: key.orbit if key else np.nan)
        out["orbit"] = out["orbit"].fillna(parsed_orbit)
    out["scene"] = pd.to_numeric(out["scene"], errors="coerce")
    if out[["orbit", "scene"]].isna().any().any():
        raise ValueError("Every catalogue row must resolve to orbit and scene")
    out["orbit"] = out["orbit"].astype(int)
    out["scene"] = out["scene"].astype(int)
    return out


def join_official_enrichment(
    catalogue: pd.DataFrame,
    scene_metadata: pd.DataFrame,
) -> pd.DataFrame:
    """Join official enrichment to CMR rows, retaining conservative defaults."""

    base = _coerce_key_columns(catalogue)
    required = {"orbit", "scene"}
    if required - set(scene_metadata.columns):
        raise ValueError("scene_metadata needs orbit and scene")
    if scene_metadata.duplicated(["orbit", "scene"]).any():
        raise ValueError("scene_metadata must have one row per orbit/scene")
    metadata = scene_metadata.rename(
        columns={
            "granule_id": "official_scene_granule_ids",
            "scene_key": "official_orbit_scene_key",
        }
    ).copy()
    overlapping = (set(base.columns) & set(metadata.columns)) - required
    base = base.drop(columns=sorted(overlapping), errors="ignore")
    out = base.merge(
        metadata,
        on=["orbit", "scene"],
        how="left",
        validate="many_to_one",
        indicator="_official_join",
    )
    missing = out["_official_join"] == "left_only"
    out.loc[missing, "geolocation_quality"] = "suspect"
    out.loc[missing, "geolocation_usable"] = False
    out.loc[missing, "obstruction_status"] = "unknown_excluded"
    out.loc[missing, "obstruction_flag"] = True
    out.loc[missing, "retrieval_band_mode"] = "unknown"
    out.loc[missing, "official_metadata_complete"] = False
    out.loc[missing, "metadata_warnings"] = (
        "No official sidecar match; scene excluded conservatively"
    )
    out["geolocation_usable"] = out["geolocation_usable"].eq(True)  # noqa: E712
    # Missing obstruction evidence is exclusionary, hence only explicit False is clear.
    out["obstruction_flag"] = ~out["obstruction_flag"].eq(False)  # noqa: E712
    out["official_metadata_complete"] = out["official_metadata_complete"].eq(
        True  # noqa: E712
    )
    return out.drop(columns="_official_join")


def summarize_domain_screening_arrays(
    view_zenith_deg: np.ndarray,
    cloud_codes: np.ndarray,
    domain_mask: np.ndarray,
    *,
    near_nadir_threshold_deg: float = 20.0,
    minimum_view_coverage: float = 0.95,
) -> dict[str, Any]:
    """Summarize view angle and cloud survival without opening an LST array.

    Cloud codes follow the official layer convention requested by the audit:
    0 clear, 1 cloud, and 255 fill.  Fill and unexpected codes do not survive.
    A pass is near-nadir only when enough domain pixels have a physical view
    angle (absolute value <= 90 degrees) and the preregistered 95th percentile
    of valid absolute angles stays within the threshold.
    """

    view_ma = np.ma.asarray(view_zenith_deg)
    cloud_ma = np.ma.asarray(cloud_codes)
    domain = np.asarray(domain_mask, dtype=bool)
    if view_ma.shape != cloud_ma.shape or view_ma.shape != domain.shape:
        raise ValueError("view_zenith, cloud, and domain masks must share one shape")
    n_domain = int(domain.sum())
    if n_domain == 0:
        raise ValueError("domain_mask contains no pixels")

    view = np.asarray(view_ma.filled(np.nan), dtype=float)
    view_masked = np.ma.getmaskarray(view_ma)
    valid_view = domain & ~view_masked & np.isfinite(view) & (np.abs(view) <= 90)
    view_values = np.abs(view[valid_view])
    n_view_valid = int(valid_view.sum())
    view_coverage = n_view_valid / n_domain
    view_max = float(np.max(view_values)) if n_view_valid else np.nan
    view_p95 = float(np.quantile(view_values, 0.95)) if n_view_valid else np.nan
    near_nadir = bool(
        n_view_valid
        and view_coverage >= minimum_view_coverage
        and view_p95 <= near_nadir_threshold_deg
    )

    cloud = np.asarray(cloud_ma.filled(255))
    cloud_masked = np.ma.getmaskarray(cloud_ma)
    clear = domain & ~cloud_masked & (cloud == 0)
    cloudy = domain & ~cloud_masked & (cloud == 1)
    fill = domain & (cloud_masked | (cloud == 255))
    known = clear | cloudy | fill
    invalid = domain & ~known
    n_clear = int(clear.sum())
    n_cloud = int(cloudy.sum())
    n_fill = int(fill.sum())
    n_invalid = int(invalid.sum())
    n_cloud_valid = n_clear + n_cloud
    return {
        "n_domain_pixels": n_domain,
        "n_view_valid_pixels": n_view_valid,
        "view_valid_fraction": view_coverage,
        "view_zenith_abs_min_deg": float(np.min(view_values))
        if n_view_valid
        else np.nan,
        "view_zenith_abs_median_deg": float(np.median(view_values))
        if n_view_valid
        else np.nan,
        "view_zenith_abs_mean_deg": float(np.mean(view_values))
        if n_view_valid
        else np.nan,
        "view_zenith_abs_p95_deg": view_p95,
        "view_zenith_abs_max_deg": view_max,
        "near_nadir_threshold_deg": float(near_nadir_threshold_deg),
        "minimum_view_coverage": float(minimum_view_coverage),
        "near_nadir": near_nadir,
        "n_clear_pixels": n_clear,
        "n_cloud_pixels": n_cloud,
        "n_cloud_fill_pixels": n_fill,
        "n_unexpected_cloud_code_pixels": n_invalid,
        "cloud_valid_fraction": n_cloud_valid / n_domain,
        "cloud_survival_fraction_of_domain": n_clear / n_domain,
        "clear_fraction_of_valid_cloud_pixels": n_clear / n_cloud_valid
        if n_cloud_valid
        else np.nan,
        "cloud_code_rule": "0=clear; 1=cloud; 255/masked=fill; other=invalid",
    }


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checkpoint(path: str | os.PathLike[str]) -> dict[str, dict[str, Any]]:
    """Load a credential-free checkpoint ledger; missing file means no work done."""

    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return {}
    document = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("items"), dict):
        raise MetadataParseError("Unsupported or malformed enrichment checkpoint")
    return document["items"]


def write_checkpoint(
    path: str | os.PathLike[str],
    items: Mapping[str, Mapping[str, Any]],
) -> None:
    """Atomically write checkpoint state without any network credential fields."""

    forbidden = {"url", "authorization", "token", "password", "cookie", "secret"}
    clean: dict[str, dict[str, Any]] = {}
    for item_id, record in items.items():
        keys = {_normalized_name(key) for key in record}
        if keys & forbidden:
            raise ValueError("Checkpoint records may not contain URLs or credentials")
        clean[str(item_id)] = dict(record)
    checkpoint_path = Path(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": clean,
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=checkpoint_path.parent,
        prefix=f".{checkpoint_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(checkpoint_path)


def record_completed_file(
    checkpoint_path: str | os.PathLike[str],
    *,
    item_id: str,
    local_path: str | os.PathLike[str],
) -> dict[str, dict[str, Any]]:
    """Record verified local evidence so an interrupted enrichment can resume."""

    file_path = Path(local_path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    items = load_checkpoint(checkpoint_path)
    items[str(item_id)] = {
        "status": "complete",
        "local_path": str(file_path),
        "size_bytes": file_path.stat().st_size,
        "sha256": _sha256(file_path),
    }
    write_checkpoint(checkpoint_path, items)
    return items


def pending_item_ids(
    item_ids: Iterable[str],
    checkpoint_items: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return IDs not backed by a still-present, size/hash-matching local file."""

    pending: list[str] = []
    for item_id in item_ids:
        record = checkpoint_items.get(str(item_id))
        if not record or record.get("status") != "complete":
            pending.append(str(item_id))
            continue
        path_value = record.get("local_path")
        if not path_value:
            pending.append(str(item_id))
            continue
        path = Path(str(path_value))
        if (
            not path.is_file()
            or path.stat().st_size != record.get("size_bytes")
            or _sha256(path) != record.get("sha256")
        ):
            pending.append(str(item_id))
    return pending
