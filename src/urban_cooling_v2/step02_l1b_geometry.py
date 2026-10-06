#!/usr/bin/env python3
"""Cloud-independent ECOSTRESS L1B GEO geometry screening (D0035).

The frozen D0035 remedy reads only three permitted swath variables:
``/Geolocation/latitude``, ``longitude``, and ``view_zenith``.  A coarse
stride-32 OPeNDAP response is used only as a locator.  Full-resolution values
are decoded from checksum-backed DMR++ chunk ranges in the protected HDF5
object.  Selected chunks start with at least a 64-source-pixel margin and are
expanded until every selected-region edge is farther than 210 m from every
canonical frozen-domain target-cell centre.

No LST, thermal-response, 2026, or holdout-result path is accepted here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit
import xml.etree.ElementTree as ET
import zlib

import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree
import shapely
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from .step02_raster import (
    VIEW_ASSET_TYPE,
    _domain_window,
    partition_domain_for_mgrs_tile,
    select_latest_tile_revisions,
)


DECISION_ID = "D0035"
EXPECTED_METADATA_CANDIDATES = 942
EXPECTED_CITY_SCENE_LINKS = 1_404
EXPECTED_UNIQUE_SCENES = 1_370
FROZEN_FIRST_YEAR = 2018
FROZEN_LAST_YEAR = 2025
COLLECTION_VERSION = 2
FULL_SWATH_SHAPE = (5_632, 5_400)
LOCATOR_STRIDE = 32
LOCATOR_MARGIN_PIXELS = 64
RADIUS_OF_INFLUENCE_M = 210.0
# The official L1 guide describes pixels growing to about 90 m at the swath
# edge.  A conservative 100 m one-pixel displacement guard ensures that an
# omitted adjacent row/column cannot move from just outside 210 m to inside it.
MAX_ADJACENT_SOURCE_DISPLACEMENT_M = 100.0
BOUNDARY_GUARD_DISTANCE_M = (
    RADIUS_OF_INFLUENCE_M + MAX_ADJACENT_SOURCE_DISPLACEMENT_M
)
# The L1 guide gives ~70 m centre and ~90 m edge pixels.  Eight kilometres is
# deliberately wider than 64 * 90 m + the 210 m final radius.  It affects only
# the initial locator; the full-resolution boundary proof is authoritative.
LOCATOR_INFLUENCE_M = 8_000.0
# D0048 permits one fail-closed initialization path when the ordinary
# stride-32 locator has no sample within the unchanged 8 km influence.  The
# fallback is deliberately bound to the exact production locator census and a
# conservative two-axis displacement bound: 2 * (32 - 1) * 100 m = 6,200 m.
NO_OVERLAP_LOCATOR_SHAPE = (176, 169)
NO_OVERLAP_LOCATOR_EXPECTED_CELLS = 29_744
NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS = 62
NO_OVERLAP_LOCATOR_UNCERTAINTY_M = 6_200.0
NO_OVERLAP_PROOF_MODE = "verified_no_overlap"
NEAR_DOMAIN_PROOF_MODE = "locator_near_domain"
NEAR_NADIR_MAX_DEG = 20.0
MINIMUM_VIEW_COVERAGE = 0.95
GEOMETRY_VARIABLES = ("latitude", "longitude", "view_zenith")
G3_AZIMUTH_VARIABLES = ("view_azimuth", "solar_azimuth")

_NO_NEAR_LOCATOR_ERROR = (
    "Stride-32 locator found no point near the assigned frozen domain"
)

_L2T_RE = re.compile(
    r"^ECOv(?P<version>\d{3})_L2T_LSTE_"
    r"(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})_"
    r"(?P<tile>[A-Z0-9]{5})_(?P<stamp>\d{8}T\d{6})_"
    r"(?P<build>\d+)_(?P<revision>\d+)$",
    re.IGNORECASE,
)
_GEO_RE = re.compile(
    r"^ECOv(?P<version>\d{3})_L1B_GEO_"
    r"(?P<orbit>\d{3,7})_(?P<scene>\d{1,3})_"
    r"(?P<stamp>\d{8}T\d{6})_"
    r"(?P<build>\d+)_(?P<revision>\d+)$",
    re.IGNORECASE,
)
_SAFE_HOSTS = {
    "opendap.earthdata.nasa.gov",
    "data.lpdaac.earthdatacloud.nasa.gov",
}
_SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_strings(values: Iterable[Any]) -> str:
    payload = "\n".join(sorted(str(value) for value in values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bool_series(series: pd.Series, *, name: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype(bool)
    lowered = series.astype("string").str.strip().str.casefold()
    if (~lowered.isin(["true", "false"])).any():
        raise ValueError(f"{name} contains non-boolean values")
    return lowered.eq("true")


def frozen_geometry_targets(
    screened_passes: pd.DataFrame,
    latest_view_manifest: pd.DataFrame,
    *,
    expected_candidates: int = EXPECTED_METADATA_CANDIDATES,
    expected_city_scene_links: int | None = EXPECTED_CITY_SCENE_LINKS,
    expected_unique_scenes: int | None = EXPECTED_UNIQUE_SCENES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the sealed 942 pass rows and their orbit/scene acquisition map."""

    pass_required = {"city", "orbit", "acquisition_utc", "metadata_candidate"}
    missing = sorted(pass_required.difference(screened_passes.columns))
    if missing:
        raise ValueError(f"Pre-cloud table lacks columns: {missing}")
    candidates = screened_passes.loc[
        _bool_series(screened_passes["metadata_candidate"], name="metadata_candidate")
    ].copy()
    candidates["city"] = candidates["city"].astype(str)
    candidates["orbit"] = pd.to_numeric(candidates["orbit"], errors="raise").astype(int)
    candidates["acquisition_utc"] = pd.to_datetime(
        candidates["acquisition_utc"], errors="raise", utc=True, format="mixed"
    )
    if len(candidates) != int(expected_candidates):
        raise ValueError(
            f"D0035 expects {expected_candidates} metadata candidates, found {len(candidates)}"
        )
    if candidates.duplicated(["city", "orbit"]).any():
        raise ValueError("D0035 candidates are not unique by city/orbit")
    years = candidates["acquisition_utc"].dt.year
    if not years.between(FROZEN_FIRST_YEAR, FROZEN_LAST_YEAR).all():
        raise ValueError("D0035 candidates must remain inside frozen 2018-2025")

    view_required = {
        "city",
        "orbit",
        "scene",
        "tile",
        "granule_id",
        "asset_type",
        "status",
        "selected_build",
        "selected_revision",
        "acquisition_utc",
    }
    missing = sorted(view_required.difference(latest_view_manifest.columns))
    if missing:
        raise ValueError(f"Latest view manifest lacks columns: {missing}")
    views = latest_view_manifest.loc[
        latest_view_manifest["asset_type"].astype(str).eq(VIEW_ASSET_TYPE)
    ].copy()
    views["orbit"] = pd.to_numeric(views["orbit"], errors="raise").astype(int)
    views["scene"] = pd.to_numeric(views["scene"], errors="raise").astype(int)
    views = views.merge(
        candidates[["city", "orbit"]],
        on=["city", "orbit"],
        how="inner",
        validate="many_to_one",
    )
    if not views["status"].astype(str).str.casefold().eq("available").all():
        raise ValueError("Every D0035 scene/tile reference must be available")
    views = select_latest_tile_revisions(views)
    parsed = views["granule_id"].astype(str).map(_L2T_RE.fullmatch)
    if parsed.isna().any():
        raise ValueError("D0035 encountered a non-v002 L2T product identity")
    if any(int(match.group("version")) != COLLECTION_VERSION for match in parsed):
        raise ValueError("D0035 scene map contains a non-v002 L2T identity")
    views["scene_acquisition_utc"] = pd.to_datetime(
        views["acquisition_utc"], errors="raise", utc=True, format="mixed"
    )
    timestamp_counts = views.groupby(["orbit", "scene"])[
        "scene_acquisition_utc"
    ].nunique()
    if not timestamp_counts.eq(1).all():
        raise ValueError("An orbit/scene maps to more than one acquisition timestamp")
    links = (
        views[
            [
                "city",
                "orbit",
                "scene",
                "scene_acquisition_utc",
            ]
        ]
        .drop_duplicates()
        .sort_values(["city", "orbit", "scene"], kind="stable")
        .reset_index(drop=True)
    )
    if expected_city_scene_links is not None and len(links) != int(
        expected_city_scene_links
    ):
        raise ValueError(
            "D0035 city/scene mapping changed: "
            f"expected {expected_city_scene_links}, found {len(links)}"
        )
    n_scenes = links[["orbit", "scene"]].drop_duplicates().shape[0]
    if expected_unique_scenes is not None and n_scenes != int(expected_unique_scenes):
        raise ValueError(
            f"D0035 unique-scene mapping changed: expected {expected_unique_scenes}, "
            f"found {n_scenes}"
        )
    expected_keys = set(map(tuple, candidates[["city", "orbit"]].to_records(index=False)))
    observed_keys = set(map(tuple, links[["city", "orbit"]].drop_duplicates().to_records(index=False)))
    if observed_keys != expected_keys:
        raise ValueError("D0035 scene links do not exactly cover the 942 pass keys")
    return (
        candidates.sort_values(["city", "acquisition_utc", "orbit"], kind="stable")
        .reset_index(drop=True),
        links,
    )


def _safe_official_url(value: Any, *, host: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() != "https" or parsed.hostname != host:
        return None
    if parsed.username or parsed.password or parsed.fragment:
        return None
    names = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if names & _SENSITIVE_QUERY_NAMES:
        return None
    return value.strip()


def normalize_geo_records(results: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Normalize cached/live CMR UMM records without opening any array values."""

    rows: list[dict[str, Any]] = []
    for result in results:
        umm = result.get("umm", result.get("UMM", {}))
        if not isinstance(umm, Mapping):
            continue
        granule_id = str(umm.get("GranuleUR", ""))
        match = _GEO_RE.fullmatch(granule_id)
        if match is None or int(match.group("version")) != COLLECTION_VERSION:
            continue
        opendap_url = None
        hdf_url = None
        for related in umm.get("RelatedUrls", ()):
            if not isinstance(related, Mapping):
                continue
            url = related.get("URL")
            if str(related.get("Subtype", "")).casefold() == "opendap data":
                opendap_url = _safe_official_url(
                    url, host="opendap.earthdata.nasa.gov"
                ) or opendap_url
            if (
                str(related.get("Type", "")).casefold() == "get data"
                and str(url).casefold().endswith(".h5")
            ):
                hdf_url = _safe_official_url(
                    url, host="data.lpdaac.earthdatacloud.nasa.gov"
                ) or hdf_url
        meta = result.get("meta", {})
        canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
        rows.append(
            {
                "granule_id": granule_id,
                "orbit": int(match.group("orbit")),
                "scene": int(match.group("scene")),
                "geo_acquisition_stamp": match.group("stamp").upper(),
                "geo_acquisition_utc": pd.to_datetime(
                    match.group("stamp"), format="%Y%m%dT%H%M%S", utc=True
                ),
                "selected_build": int(match.group("build")),
                "selected_revision": int(match.group("revision")),
                "cmr_revision_id": int(meta.get("revision-id", 0) or 0),
                "concept_id": str(meta.get("concept-id", "")),
                "collection_concept_id": str(meta.get("collection-concept-id", "")),
                "size_mb": pd.to_numeric(result.get("size"), errors="coerce"),
                "opendap_url": opendap_url,
                "hdf_url": hdf_url,
                "dmrpp_url": hdf_url + ".dmrpp" if hdf_url is not None else None,
                "required_endpoints_complete": bool(
                    opendap_url is not None and hdf_url is not None
                ),
                "cmr_record_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "granule_id",
                "orbit",
                "scene",
                "geo_acquisition_utc",
                "selected_build",
                "selected_revision",
            ]
        )
    return pd.DataFrame(rows).drop_duplicates(
        ["granule_id", "cmr_revision_id"], keep="last"
    )


def resolve_latest_geo_scenes(
    scene_links: pd.DataFrame,
    geo_records: pd.DataFrame,
    *,
    expected_unique_scenes: int = EXPECTED_UNIQUE_SCENES,
) -> pd.DataFrame:
    """Resolve one latest v002 GEO object per exact orbit/scene/acquisition."""

    expected = scene_links[
        ["orbit", "scene", "scene_acquisition_utc"]
    ].drop_duplicates()
    if len(expected) != int(expected_unique_scenes):
        raise ValueError("Unexpected D0035 unique-scene count before GEO resolution")
    expected = expected.copy()
    expected["scene_acquisition_second"] = pd.to_datetime(
        expected["scene_acquisition_utc"], utc=True, format="mixed"
    ).dt.floor("s")
    records = geo_records.copy()
    if records.empty:
        # A zero-result (or fully failed) exact-scene CMR census is still an
        # auditable result.  Preserve all expected rows as explicit ``missing``
        # identities so the caller can write the sealed 1,370-row manifest
        # before stopping.
        resolved = expected.copy()
        for column in (
            "granule_id",
            "geo_acquisition_stamp",
            "geo_acquisition_utc",
            "concept_id",
            "collection_concept_id",
            "opendap_url",
            "hdf_url",
            "dmrpp_url",
            "cmr_record_sha256",
        ):
            resolved[column] = pd.NA
        for column in (
            "selected_build",
            "selected_revision",
            "cmr_revision_id",
            "size_mb",
        ):
            resolved[column] = np.nan
        resolved["required_endpoints_complete"] = False
        resolved["status"] = "missing"
        return resolved.sort_values(["orbit", "scene"], kind="stable").reset_index(
            drop=True
        )
    records["geo_acquisition_utc"] = pd.to_datetime(
        records["geo_acquisition_utc"], errors="raise", utc=True, format="mixed"
    )
    joined = records.merge(
        expected,
        on=["orbit", "scene"],
        how="inner",
        validate="many_to_one",
    )
    joined = joined.loc[
        joined["geo_acquisition_utc"].eq(joined["scene_acquisition_second"])
    ].copy()
    joined = joined.sort_values(
        [
            "orbit",
            "scene",
            "selected_build",
            "selected_revision",
            "cmr_revision_id",
            "granule_id",
        ],
        kind="stable",
    ).drop_duplicates(["orbit", "scene"], keep="last")
    resolved = expected.merge(
        joined.drop(columns=["scene_acquisition_utc", "scene_acquisition_second"]),
        on=["orbit", "scene"],
        how="left",
        validate="one_to_one",
    )
    resolved["status"] = np.select(
        [
            resolved["granule_id"].isna(),
            ~resolved["required_endpoints_complete"].fillna(False).astype(bool),
        ],
        ["missing", "missing_required_endpoint"],
        default="available",
    )
    if len(resolved) != int(expected_unique_scenes):
        raise ValueError("Resolved GEO scene manifest changed cardinality")
    return resolved.sort_values(["orbit", "scene"], kind="stable").reset_index(
        drop=True
    )


@dataclass(frozen=True)
class TargetGrid:
    city: str
    tile: str
    crs: CRS
    x: np.ndarray
    y: np.ndarray
    tree: cKDTree = field(repr=False, compare=False)
    domain_geometry_projected: Any | None = field(
        default=None, repr=False, compare=False
    )

    @property
    def size(self) -> int:
        return int(self.x.size)


def build_canonical_target_grids(
    latest_view_manifest: pd.DataFrame,
    *,
    domain_geometries_wgs84: Mapping[str, Mapping[str, Any]],
    asset_root: str | Path,
    denominator_table: pd.DataFrame,
) -> dict[str, dict[str, TargetGrid]]:
    """Build canonical 70 m target-cell centres using COG headers only."""

    views = latest_view_manifest.loc[
        latest_view_manifest["asset_type"].astype(str).eq(VIEW_ASSET_TYPE)
    ].copy()
    views["orbit"] = pd.to_numeric(views["orbit"], errors="raise").astype(int)
    views["scene"] = pd.to_numeric(views["scene"], errors="raise").astype(int)
    views = select_latest_tile_revisions(views)
    root = Path(asset_root)
    expected = denominator_table.copy()
    expected["n_domain_pixel_centers"] = pd.to_numeric(
        expected["n_domain_pixel_centers"], errors="raise"
    ).astype(int)
    expected_counts = {
        (str(row.city), str(row.tile)): int(row.n_domain_pixel_centers)
        for row in expected.itertuples(index=False)
    }
    grids: dict[str, dict[str, TargetGrid]] = defaultdict(dict)
    for city, tile in sorted(expected_counts):
        rows = views.loc[
            views["city"].astype(str).eq(city) & views["tile"].astype(str).eq(tile)
        ]
        if rows.empty:
            raise ValueError(f"No reference COG header for {city}/{tile}")
        record = rows.sort_values(
            ["scene", "selected_build", "selected_revision", "granule_id"],
            kind="stable",
        ).iloc[0]
        path = root / VIEW_ASSET_TYPE / Path(str(record["file_name"])).name
        if not path.is_file():
            raise FileNotFoundError(path)
        tile_domain = partition_domain_for_mgrs_tile(
            domain_geometries_wgs84[city], tile
        )
        with rasterio.open(path) as dataset:
            clipped = _domain_window(dataset, tile_domain)
            crs = CRS.from_user_input(dataset.crs)
            if clipped is None:
                x = np.array([], dtype=np.float64)
                y = np.array([], dtype=np.float64)
            else:
                window, mask = clipped
                transform = dataset.window_transform(window)
                row_index, col_index = np.nonzero(mask)
                # Affine transforms are retained in full precision.  ECOSTRESS
                # tiled grids are north-up, but the general formula costs no more.
                col = col_index.astype(np.float64) + 0.5
                row = row_index.astype(np.float64) + 0.5
                x = transform.c + transform.a * col + transform.b * row
                y = transform.f + transform.d * col + transform.e * row
                x = np.asarray(x, dtype=np.float64)
                y = np.asarray(y, dtype=np.float64)
        found = int(x.size)
        if found != expected_counts[(city, tile)]:
            raise ValueError(
                f"Canonical target count changed for {city}/{tile}: "
                f"expected {expected_counts[(city, tile)]}, found {found}"
            )
        if found:
            transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            projected_domain = shapely_transform(
                transformer.transform, shape(tile_domain)
            )
            grids[city][tile] = TargetGrid(
                city=city,
                tile=tile,
                crs=crs,
                x=x,
                y=y,
                tree=cKDTree(np.column_stack((x, y))),
                domain_geometry_projected=projected_domain,
            )
    for city, group in expected.groupby("city", sort=True):
        expected_total = int(group["city_domain_pixel_denominator"].iloc[0])
        found_total = sum(grid.size for grid in grids[str(city)].values())
        if found_total != expected_total:
            raise ValueError(
                f"Canonical city denominator changed for {city}: "
                f"expected {expected_total}, found {found_total}"
            )
    return {city: dict(value) for city, value in grids.items()}


@dataclass(frozen=True)
class ChunkDescriptor:
    variable: str
    dtype: np.dtype
    array_shape: tuple[int, int]
    chunk_shape: tuple[int, int]
    origin: tuple[int, int]
    offset: int
    nbytes: int
    compression: str
    byte_order: str
    fill_value: str | None

    @property
    def coord(self) -> tuple[int, int]:
        return (
            self.origin[0] // self.chunk_shape[0],
            self.origin[1] // self.chunk_shape[1],
        )


def parse_dmrpp_chunks_for_variables(
    path: str | Path,
    variables: Sequence[str],
) -> dict[str, dict[tuple[int, int], ChunkDescriptor]]:
    """Parse an explicit allow-list of nonthermal Geolocation chunk maps."""

    ns = {
        "d": "http://xml.opendap.org/ns/DAP/4.0#",
        "p": "http://xml.opendap.org/dap/dmrpp/1.0.0#",
    }
    root = ET.parse(path).getroot()
    group = root.find("d:Group[@name='Geolocation']", ns)
    if group is None:
        raise ValueError("DMR++ lacks /Geolocation")
    type_map = {"Float64": np.dtype("f8"), "Float32": np.dtype("f4")}
    expected_types = {
        "latitude": "Float64",
        "longitude": "Float64",
        "view_zenith": "Float32",
        "view_azimuth": "Float32",
        "solar_azimuth": "Float32",
    }
    requested = tuple(str(value) for value in variables)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("DMR++ variable allow-list must be nonempty and unique")
    forbidden = sorted(set(requested).difference(expected_types))
    if forbidden:
        raise ValueError(f"Forbidden nonthermal Geolocation variables {forbidden}")
    output: dict[str, dict[tuple[int, int], ChunkDescriptor]] = {}
    for variable in requested:
        element = next(
            (child for child in group if child.attrib.get("name") == variable), None
        )
        if element is None:
            raise ValueError(f"DMR++ lacks /Geolocation/{variable}")
        kind = element.tag.split("}")[-1]
        if kind != expected_types[variable]:
            raise ValueError(f"Unexpected {variable} type {kind}")
        array_shape = tuple(int(dim.attrib["size"]) for dim in element.findall("d:Dim", ns))
        if array_shape != FULL_SWATH_SHAPE:
            raise ValueError(f"Unexpected {variable} shape {array_shape}")
        chunks = element.find("p:chunks", ns)
        if chunks is None:
            raise ValueError(f"DMR++ lacks chunk metadata for {variable}")
        compression = str(chunks.attrib.get("compressionType", ""))
        if compression.casefold() != "deflate":
            raise ValueError(f"Unsupported {variable} compression {compression!r}")
        byte_order = str(chunks.attrib.get("byteOrder", ""))
        if byte_order not in {"LE", "BE"}:
            raise ValueError(f"Unsupported {variable} byte order {byte_order!r}")
        text = chunks.findtext("p:chunkDimensionSizes", default="", namespaces=ns)
        chunk_shape = tuple(int(value) for value in text.split())
        if len(chunk_shape) != 2 or min(chunk_shape) <= 0:
            raise ValueError(f"Invalid {variable} chunk dimensions")
        descriptors: dict[tuple[int, int], ChunkDescriptor] = {}
        for chunk in chunks.findall("p:chunk", ns):
            try:
                position = tuple(
                    int(value)
                    for value in str(chunk.attrib["chunkPositionInArray"])
                    .strip("[]")
                    .split(",")
                )
                offset = int(chunk.attrib["offset"])
                nbytes = int(chunk.attrib["nBytes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Malformed {variable} chunk metadata") from exc
            if (
                len(position) != 2
                or any(value < 0 for value in position)
                or any(value >= size for value, size in zip(position, array_shape))
                or any(value % size for value, size in zip(position, chunk_shape))
            ):
                raise ValueError(f"Invalid {variable} chunk origin {position}")
            if offset < 0 or nbytes <= 0:
                raise ValueError(
                    f"Invalid {variable} chunk byte range offset={offset}, nBytes={nbytes}"
                )
            descriptor = ChunkDescriptor(
                variable=variable,
                dtype=type_map[kind],
                array_shape=array_shape,
                chunk_shape=chunk_shape,
                origin=position,
                offset=offset,
                nbytes=nbytes,
                compression=compression,
                byte_order=byte_order,
                fill_value=chunks.attrib.get("fillValue"),
            )
            if descriptor.coord in descriptors:
                raise ValueError(f"Duplicate {variable} chunk {descriptor.coord}")
            descriptors[descriptor.coord] = descriptor
        expected_chunk_count = math.ceil(array_shape[0] / chunk_shape[0]) * math.ceil(
            array_shape[1] / chunk_shape[1]
        )
        if len(descriptors) != expected_chunk_count:
            raise ValueError(
                f"Incomplete {variable} chunk map: {len(descriptors)}/{expected_chunk_count}"
            )
        output[variable] = descriptors
    shapes = {
        descriptor.chunk_shape
        for values in output.values()
        for descriptor in values.values()
    }
    coords = [set(values) for values in output.values()]
    if len(shapes) != 1 or not all(value == coords[0] for value in coords[1:]):
        raise ValueError("D0035 variable chunk grids do not align")
    return output


def parse_dmrpp_chunks(path: str | Path) -> dict[str, dict[tuple[int, int], ChunkDescriptor]]:
    """Parse only the three frozen D0035 variable chunk maps."""

    return parse_dmrpp_chunks_for_variables(path, GEOMETRY_VARIABLES)


def decode_chunk(payload: bytes, descriptor: ChunkDescriptor) -> np.ndarray:
    """Inflate one HDF5 chunk and return its full stored chunk shape."""

    try:
        raw = zlib.decompress(payload)
    except zlib.error as exc:
        raise ValueError(f"Cannot inflate {descriptor.variable} chunk {descriptor.coord}") from exc
    order = "<" if descriptor.byte_order == "LE" else ">"
    dtype = descriptor.dtype.newbyteorder(order)
    expected = int(np.prod(descriptor.chunk_shape)) * dtype.itemsize
    if len(raw) != expected:
        raise ValueError(
            f"Decoded {descriptor.variable} chunk {descriptor.coord} has "
            f"{len(raw)} bytes, expected {expected}"
        )
    return np.frombuffer(raw, dtype=dtype).reshape(descriptor.chunk_shape).astype(
        descriptor.dtype, copy=False
    )


def coalesce_chunk_ranges(
    descriptors: Sequence[ChunkDescriptor],
    *,
    max_span_bytes: int = 16 * 1024 * 1024,
    max_gap_bytes: int = 64 * 1024,
) -> list[tuple[int, int, tuple[ChunkDescriptor, ...]]]:
    """Combine nearby chunk byte ranges without bridging large HDF5 gaps."""

    if max_span_bytes <= 0 or max_gap_bytes < 0:
        raise ValueError("Range coalescing limits must be non-negative")
    ordered = sorted(descriptors, key=lambda item: (item.offset, item.nbytes))
    groups: list[tuple[int, int, tuple[ChunkDescriptor, ...]]] = []
    current: list[ChunkDescriptor] = []
    start = end = 0
    for descriptor in ordered:
        item_start = descriptor.offset
        item_end = descriptor.offset + descriptor.nbytes - 1
        if not current:
            current = [descriptor]
            start, end = item_start, item_end
            continue
        proposed_end = max(end, item_end)
        gap = max(0, item_start - end - 1)
        if gap <= max_gap_bytes and proposed_end - start + 1 <= max_span_bytes:
            current.append(descriptor)
            end = proposed_end
        else:
            groups.append((start, end, tuple(current)))
            current = [descriptor]
            start, end = item_start, item_end
    if current:
        groups.append((start, end, tuple(current)))
    return groups


def decode_selected_chunks(
    descriptors: Mapping[str, Mapping[tuple[int, int], ChunkDescriptor]],
    coords: set[tuple[int, int]],
    variables: Sequence[str],
    *,
    fetch_range: Callable[[int, int], bytes],
    decoded: dict[str, dict[tuple[int, int], np.ndarray]] | None = None,
    chunk_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, dict[tuple[int, int], np.ndarray]], dict[str, str], int]:
    """Fetch/decode only missing selected chunks through a range callback."""

    output = decoded if decoded is not None else {name: {} for name in descriptors}
    for name in descriptors:
        output.setdefault(name, {})
    hashes = chunk_hashes if chunk_hashes is not None else {}
    needed: list[ChunkDescriptor] = []
    for variable in variables:
        if variable not in descriptors:
            raise ValueError(f"Variable {variable!r} is absent from the parsed DMR++ allow-list")
        missing = coords.difference(output[variable])
        absent = missing.difference(descriptors[variable])
        if absent:
            raise ValueError(f"DMR++ is missing selected {variable} chunks")
        needed.extend(descriptors[variable][coord] for coord in sorted(missing))
    requests = 0
    for start, end, group in coalesce_chunk_ranges(needed):
        payload = fetch_range(start, end)
        requests += 1
        if len(payload) != end - start + 1:
            raise ValueError("HTTP byte-range payload length mismatch")
        for descriptor in group:
            begin = descriptor.offset - start
            compressed = payload[begin : begin + descriptor.nbytes]
            if len(compressed) != descriptor.nbytes:
                raise ValueError("Coalesced response omitted a selected chunk")
            key = f"{descriptor.variable}:{descriptor.coord[0]}:{descriptor.coord[1]}"
            hashes[key] = hashlib.sha256(compressed).hexdigest()
            output[descriptor.variable][descriptor.coord] = decode_chunk(
                compressed, descriptor
            )
    return output, hashes, requests


def locator_indices(length: int, stride: int = LOCATOR_STRIDE) -> np.ndarray:
    if length <= 0 or stride <= 0:
        raise ValueError("Locator dimensions and stride must be positive")
    return np.arange(0, length, stride, dtype=np.int32)


def initial_chunk_selection(
    locator_latitude: np.ndarray,
    locator_longitude: np.ndarray,
    target_grids: Mapping[str, TargetGrid],
    *,
    chunk_shape: tuple[int, int],
    locator_stride: int = LOCATOR_STRIDE,
    source_margin_pixels: int = LOCATOR_MARGIN_PIXELS,
    locator_influence_m: float = LOCATOR_INFLUENCE_M,
    array_shape: tuple[int, int] = FULL_SWATH_SHAPE,
) -> set[tuple[int, int]]:
    """Select initial chunks around coarse points near any domain target cell."""

    lat = np.asarray(locator_latitude, dtype=float)
    lon = np.asarray(locator_longitude, dtype=float)
    expected_shape = (
        len(locator_indices(array_shape[0], locator_stride)),
        len(locator_indices(array_shape[1], locator_stride)),
    )
    if lat.shape != expected_shape or lon.shape != expected_shape:
        raise ValueError(
            f"Unexpected stride locator shape {lat.shape}/{lon.shape}; expected {expected_shape}"
        )
    valid = (
        np.isfinite(lat)
        & np.isfinite(lon)
        & (lat >= -90)
        & (lat <= 90)
        & (lon >= -180)
        & (lon <= 180)
        & ~((lat == 0) & (lon == 0))
    )
    near = np.zeros(lat.shape, dtype=bool)
    flat_valid = np.flatnonzero(valid)
    if flat_valid.size:
        valid_lon = lon.ravel()[flat_valid]
        valid_lat = lat.ravel()[flat_valid]
        for grid in target_grids.values():
            transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
            x, y = transformer.transform(valid_lon, valid_lat)
            xy = np.column_stack((x, y))
            finite = np.isfinite(xy).all(axis=1)
            distance = np.full(len(xy), np.inf, dtype=float)
            if finite.any():
                distance[finite] = grid.tree.query(
                    xy[finite], k=1, distance_upper_bound=locator_influence_m
                )[0]
            near.ravel()[flat_valid[distance <= locator_influence_m]] = True
    if not near.any():
        raise ValueError(_NO_NEAR_LOCATOR_ERROR)
    row_samples = locator_indices(array_shape[0], locator_stride)
    col_samples = locator_indices(array_shape[1], locator_stride)
    n_chunk_rows = math.ceil(array_shape[0] / chunk_shape[0])
    n_chunk_cols = math.ceil(array_shape[1] / chunk_shape[1])
    selected: set[tuple[int, int]] = set()
    for locator_row, locator_col in np.argwhere(near):
        row = int(row_samples[locator_row])
        col = int(col_samples[locator_col])
        r0 = max(0, row - source_margin_pixels)
        r1 = min(array_shape[0] - 1, row + source_margin_pixels)
        c0 = max(0, col - source_margin_pixels)
        c1 = min(array_shape[1] - 1, col + source_margin_pixels)
        for chunk_row in range(r0 // chunk_shape[0], r1 // chunk_shape[0] + 1):
            for chunk_col in range(c0 // chunk_shape[1], c1 // chunk_shape[1] + 1):
                if 0 <= chunk_row < n_chunk_rows and 0 <= chunk_col < n_chunk_cols:
                    selected.add((chunk_row, chunk_col))
    if not selected:
        raise ValueError("Stride locator produced an empty full-resolution chunk selection")
    return selected


def _chunks_around_locator_samples(
    locator_samples: Sequence[tuple[int, int]],
    *,
    chunk_shape: tuple[int, int],
    locator_stride: int,
    source_margin_pixels: int,
    array_shape: tuple[int, int],
) -> set[tuple[int, int]]:
    """Return chunks around deterministic locator-array indices."""

    row_samples = locator_indices(array_shape[0], locator_stride)
    col_samples = locator_indices(array_shape[1], locator_stride)
    n_chunk_rows = math.ceil(array_shape[0] / chunk_shape[0])
    n_chunk_cols = math.ceil(array_shape[1] / chunk_shape[1])
    selected: set[tuple[int, int]] = set()
    for locator_row, locator_col in locator_samples:
        if not (
            0 <= int(locator_row) < len(row_samples)
            and 0 <= int(locator_col) < len(col_samples)
        ):
            raise ValueError("D0048 locator seed is outside the frozen locator array")
        row = int(row_samples[int(locator_row)])
        col = int(col_samples[int(locator_col)])
        r0 = max(0, row - source_margin_pixels)
        r1 = min(array_shape[0] - 1, row + source_margin_pixels)
        c0 = max(0, col - source_margin_pixels)
        c1 = min(array_shape[1] - 1, col + source_margin_pixels)
        for chunk_row in range(r0 // chunk_shape[0], r1 // chunk_shape[0] + 1):
            for chunk_col in range(c0 // chunk_shape[1], c1 // chunk_shape[1] + 1):
                if 0 <= chunk_row < n_chunk_rows and 0 <= chunk_col < n_chunk_cols:
                    selected.add((chunk_row, chunk_col))
    if not selected:
        raise ValueError("D0048 verified-no-overlap seeds produced no chunks")
    return selected


def initial_chunk_selection_with_proof(
    locator_latitude: np.ndarray,
    locator_longitude: np.ndarray,
    target_grids: Mapping[str, TargetGrid],
    *,
    chunk_shape: tuple[int, int],
    locator_stride: int = LOCATOR_STRIDE,
    source_margin_pixels: int = LOCATOR_MARGIN_PIXELS,
    locator_influence_m: float = LOCATOR_INFLUENCE_M,
    array_shape: tuple[int, int] = FULL_SWATH_SHAPE,
) -> tuple[set[tuple[int, int]], dict[str, Any]]:
    """Select ordinary near-domain chunks or prove a D0048 empty scene.

    The ordinary D0035 selector is called first and is therefore unchanged for
    every scene with at least one locator point inside 8 km.  D0048 is reached
    only for its exact ``no point near`` outcome.  It requires a fully valid
    176x169 locator and a conservative global lower bound relative to each
    literal frozen-domain geometry before seeding one row-major-stable nearest
    locator sample per target grid.
    """

    lat = np.asarray(locator_latitude, dtype=float)
    lon = np.asarray(locator_longitude, dtype=float)
    try:
        selected = initial_chunk_selection(
            lat,
            lon,
            target_grids,
            chunk_shape=chunk_shape,
            locator_stride=locator_stride,
            source_margin_pixels=source_margin_pixels,
            locator_influence_m=locator_influence_m,
            array_shape=array_shape,
        )
    except ValueError as exc:
        if str(exc) != _NO_NEAR_LOCATOR_ERROR:
            raise
    else:
        valid_count = int(_valid_geo(lat, lon).sum())
        return selected, {
            "proof_mode": NEAR_DOMAIN_PROOF_MODE,
            "proof_status": "near_domain_selected_pending_full_resolution",
            "locator_shape": [int(value) for value in lat.shape],
            "locator_stride": int(locator_stride),
            "locator_stride_minus_one_pixels": LOCATOR_STRIDE - 1,
            "locator_influence_m": float(locator_influence_m),
            "locator_valid_count": valid_count,
            "locator_expected_count": int(lat.size),
            "locator_max_unsampled_path_pixels": NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS,
            "maximum_adjacent_source_displacement_m": MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
            "locator_minimum_domain_distance_m": None,
            "locator_uncertainty_bound_m": NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
            "locator_no_overlap_lower_bound_m": None,
            "boundary_guard_distance_m": BOUNDARY_GUARD_DISTANCE_M,
            "seed_source_margin_pixels": int(source_margin_pixels),
            "row_major_tie_breaking": True,
            "seeded_locator_points": [],
            "seeded_chunk_coords": [list(coord) for coord in sorted(selected)],
            "seeded_chunk_count": int(len(selected)),
            "full_resolution_boundary_verified": False,
            "mapped_target_cell_count": None,
            "geometry_observation_status": None,
            "proof_acceptance_status": None,
            "verified_no_overlap_mapped_zero": False,
            "verified_no_overlap_zero_imputed": False,
            "missing_scene_zero_coverage_assigned": False,
            "missing_scene_substitution_used": False,
        }

    # The fallback proof constants are frozen and cannot be relaxed through a
    # caller argument.  These checks also keep small synthetic uses of the
    # ordinary selector from accidentally entering the production proof path.
    if tuple(lat.shape) != NO_OVERLAP_LOCATOR_SHAPE or tuple(lon.shape) != (
        NO_OVERLAP_LOCATOR_SHAPE
    ):
        raise ValueError(
            "D0048 verified-no-overlap requires the exact 176x169 locator shape"
        )
    if (
        tuple(array_shape) != FULL_SWATH_SHAPE
        or int(locator_stride) != LOCATOR_STRIDE
        or int(source_margin_pixels) != LOCATOR_MARGIN_PIXELS
        or float(locator_influence_m) != LOCATOR_INFLUENCE_M
    ):
        raise ValueError("D0048 verified-no-overlap constants differ from the frozen seal")
    valid = _valid_geo(lat, lon)
    valid_count = int(valid.sum())
    if valid_count != NO_OVERLAP_LOCATOR_EXPECTED_CELLS:
        raise ValueError(
            "D0048 verified-no-overlap requires all 29,744 locator cells valid"
        )
    if not target_grids:
        raise ValueError("D0048 verified-no-overlap requires a frozen target grid")

    flat_lat = lat.ravel(order="C")
    flat_lon = lon.ravel(order="C")
    row_samples = locator_indices(array_shape[0], locator_stride)
    col_samples = locator_indices(array_shape[1], locator_stride)
    seeded_points: list[dict[str, Any]] = []
    seed_indices: list[tuple[int, int]] = []
    global_minimum = math.inf
    for target_name, grid in sorted(target_grids.items(), key=lambda item: str(item[0])):
        domain = grid.domain_geometry_projected
        if domain is None or bool(domain.is_empty):
            raise ValueError(
                "D0048 verified-no-overlap requires literal frozen-domain geometry"
            )
        transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        x, y = transformer.transform(flat_lon, flat_lat)
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if not (np.isfinite(x).all() and np.isfinite(y).all()):
            raise ValueError("D0048 locator projection contains non-finite coordinates")
        distances = np.asarray(
            shapely.distance(domain, shapely.points(x, y)), dtype=float
        )
        if distances.shape != (NO_OVERLAP_LOCATOR_EXPECTED_CELLS,) or not (
            np.isfinite(distances).all() and (distances >= 0).all()
        ):
            raise ValueError("D0048 literal-domain distances are not finite and complete")
        # np.argmin returns the first occurrence.  C-order flattening therefore
        # implements the frozen row-major-lowest-flat-index tie break.
        flat_index = int(np.argmin(distances))
        locator_row, locator_col = np.unravel_index(
            flat_index, NO_OVERLAP_LOCATOR_SHAPE, order="C"
        )
        minimum = float(distances[flat_index])
        global_minimum = min(global_minimum, minimum)
        seed_indices.append((int(locator_row), int(locator_col)))
        seeded_points.append(
            {
                "target_grid": str(target_name),
                "locator_flat_index": flat_index,
                "locator_row": int(locator_row),
                "locator_col": int(locator_col),
                "source_row": int(row_samples[int(locator_row)]),
                "source_col": int(col_samples[int(locator_col)]),
                "latitude": float(flat_lat[flat_index]),
                "longitude": float(flat_lon[flat_index]),
                "minimum_domain_distance_m": minimum,
            }
        )

    lower_bound = global_minimum - NO_OVERLAP_LOCATOR_UNCERTAINTY_M
    if not lower_bound > BOUNDARY_GUARD_DISTANCE_M:
        raise ValueError(
            "D0048 verified-no-overlap lower bound does not exceed the 310 m guard"
        )
    selected = _chunks_around_locator_samples(
        seed_indices,
        chunk_shape=chunk_shape,
        locator_stride=locator_stride,
        source_margin_pixels=source_margin_pixels,
        array_shape=array_shape,
    )
    return selected, {
        "proof_mode": NO_OVERLAP_PROOF_MODE,
        "proof_status": "locator_global_lower_bound_verified_pending_full_resolution",
        "locator_shape": [int(value) for value in lat.shape],
        "locator_stride": LOCATOR_STRIDE,
        "locator_stride_minus_one_pixels": LOCATOR_STRIDE - 1,
        "locator_influence_m": LOCATOR_INFLUENCE_M,
        "locator_valid_count": valid_count,
        "locator_expected_count": NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
        "locator_max_unsampled_path_pixels": NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS,
        "maximum_adjacent_source_displacement_m": MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
        "locator_minimum_domain_distance_m": global_minimum,
        "locator_uncertainty_bound_m": NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
        "locator_no_overlap_lower_bound_m": lower_bound,
        "boundary_guard_distance_m": BOUNDARY_GUARD_DISTANCE_M,
        "seed_source_margin_pixels": LOCATOR_MARGIN_PIXELS,
        "row_major_tie_breaking": True,
        "seeded_locator_points": seeded_points,
        "seeded_chunk_coords": [list(coord) for coord in sorted(selected)],
        "seeded_chunk_count": int(len(selected)),
        "full_resolution_boundary_verified": False,
        "mapped_target_cell_count": None,
        "geometry_observation_status": None,
        "proof_acceptance_status": None,
        "verified_no_overlap_mapped_zero": False,
        "verified_no_overlap_zero_imputed": False,
        "missing_scene_zero_coverage_assigned": False,
        "missing_scene_substitution_used": False,
    }


def finalize_initial_selection_proof(
    proof: Mapping[str, Any],
    *,
    full_resolution_boundary_verified: bool,
    mapped_target_cell_count: int,
) -> dict[str, Any]:
    """Finalize D0048 scene proof and reject any empty-proof contradiction."""

    output = dict(proof)
    mapped_count = int(mapped_target_cell_count)
    if mapped_count < 0:
        raise ValueError("Mapped target-cell count cannot be negative")
    output["full_resolution_boundary_verified"] = bool(
        full_resolution_boundary_verified
    )
    # The downstream zero-map predicate requires an explicit generic boundary
    # seal as well as the full-resolution-specific seal. They describe the
    # same completed verification at this finalization boundary.
    output["boundary_verified"] = bool(full_resolution_boundary_verified)
    output["mapped_target_cell_count"] = mapped_count
    if not full_resolution_boundary_verified:
        raise ValueError("Full-resolution boundary proof is incomplete")
    if output.get("proof_mode") == NO_OVERLAP_PROOF_MODE:
        if mapped_count != 0:
            raise ValueError(
                "D0048 verified-no-overlap contradiction: target cells were mapped"
            )
        output["proof_status"] = "verified_no_domain_overlap"
        output["proof_acceptance_status"] = "verified_no_overlap_mapped_zero"
        output["geometry_observation_status"] = "verified_no_domain_overlap"
        output["verified_no_overlap_mapped_zero"] = True
        output["verified_no_overlap_zero_imputed"] = False
    elif output.get("proof_mode") == NEAR_DOMAIN_PROOF_MODE:
        output["proof_status"] = "near_domain_full_resolution_verified"
        output["proof_acceptance_status"] = "ordinary_near_domain_mapping"
        output["geometry_observation_status"] = "mapped_near_domain_geometry"
        output["verified_no_overlap_mapped_zero"] = False
        output["verified_no_overlap_zero_imputed"] = False
    else:
        raise ValueError("Unknown initial geometry proof mode")
    return output


def _valid_geo(latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    return (
        np.isfinite(latitude)
        & np.isfinite(longitude)
        & (latitude >= -90)
        & (latitude <= 90)
        & (longitude >= -180)
        & (longitude <= 180)
        & ~((latitude == 0) & (longitude == 0))
    )


def _minimum_target_distance(
    longitude: np.ndarray,
    latitude: np.ndarray,
    target_grids: Mapping[str, TargetGrid],
    *,
    upper_bound: float = np.inf,
) -> float:
    valid = _valid_geo(latitude, longitude)
    if not valid.any():
        return math.inf
    lon = np.asarray(longitude[valid], dtype=float)
    lat = np.asarray(latitude[valid], dtype=float)
    best = math.inf
    for grid in target_grids.values():
        transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        x, y = transformer.transform(lon, lat)
        xy = np.column_stack((x, y))
        finite = np.isfinite(xy).all(axis=1)
        if not finite.any():
            continue
        distance = grid.tree.query(
            xy[finite], k=1, distance_upper_bound=upper_bound
        )[0]
        if len(distance):
            best = min(best, float(np.min(distance)))
    return best


def _minimum_domain_distance(
    longitude: np.ndarray,
    latitude: np.ndarray,
    target_grids: Mapping[str, TargetGrid],
) -> tuple[float, int]:
    """Return minimum projected distance to the literal frozen domain.

    Tests and small synthetic callers may omit ``domain_geometry_projected``;
    for those only, the canonical target-cell tree is the exact fallback.
    """

    valid = _valid_geo(latitude, longitude)
    valid_count = int(valid.sum())
    if not valid_count:
        return math.inf, 0
    lon = np.asarray(longitude[valid], dtype=float)
    lat = np.asarray(latitude[valid], dtype=float)
    best = math.inf
    for grid in target_grids.values():
        transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        x, y = transformer.transform(lon, lat)
        finite = np.isfinite(x) & np.isfinite(y)
        if not finite.any():
            continue
        if grid.domain_geometry_projected is not None:
            points = shapely.points(np.asarray(x)[finite], np.asarray(y)[finite])
            distance = shapely.distance(grid.domain_geometry_projected, points)
        else:
            distance = grid.tree.query(
                np.column_stack((np.asarray(x)[finite], np.asarray(y)[finite])), k=1
            )[0]
        if len(distance):
            best = min(best, float(np.min(distance)))
    return best, valid_count


def boundary_expansion_neighbors(
    selected: set[tuple[int, int]],
    latitude_chunks: Mapping[tuple[int, int], np.ndarray],
    longitude_chunks: Mapping[tuple[int, int], np.ndarray],
    target_grids: Mapping[str, TargetGrid],
    *,
    chunk_shape: tuple[int, int],
    array_shape: tuple[int, int] = FULL_SWATH_SHAPE,
    radius_m: float = RADIUS_OF_INFLUENCE_M,
    adjacent_displacement_guard_m: float = MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
) -> tuple[set[tuple[int, int]], float, int]:
    """Return omitted neighbor chunks whose selected edge is within 210 m."""

    n_chunk_rows = math.ceil(array_shape[0] / chunk_shape[0])
    n_chunk_cols = math.ceil(array_shape[1] / chunk_shape[1])
    add: set[tuple[int, int]] = set()
    minimum = math.inf
    n_edges = 0
    directions = (
        (-1, 0, "north"),
        (1, 0, "south"),
        (0, -1, "west"),
        (0, 1, "east"),
    )
    for coord in sorted(selected):
        if coord not in latitude_chunks or coord not in longitude_chunks:
            raise ValueError("Boundary proof lacks decoded latitude/longitude chunks")
        latitude = latitude_chunks[coord]
        longitude = longitude_chunks[coord]
        row_origin = coord[0] * chunk_shape[0]
        col_origin = coord[1] * chunk_shape[1]
        valid_rows = min(chunk_shape[0], array_shape[0] - row_origin)
        valid_cols = min(chunk_shape[1], array_shape[1] - col_origin)
        for dr, dc, side in directions:
            neighbor = (coord[0] + dr, coord[1] + dc)
            in_array = (
                0 <= neighbor[0] < n_chunk_rows
                and 0 <= neighbor[1] < n_chunk_cols
            )
            if not in_array or neighbor in selected:
                continue
            n_edges += 1
            if side == "north":
                edge_lat = latitude[0, :valid_cols]
                edge_lon = longitude[0, :valid_cols]
            elif side == "south":
                edge_lat = latitude[valid_rows - 1, :valid_cols]
                edge_lon = longitude[valid_rows - 1, :valid_cols]
            elif side == "west":
                edge_lat = latitude[:valid_rows, 0]
                edge_lon = longitude[:valid_rows, 0]
            else:
                edge_lat = latitude[:valid_rows, valid_cols - 1]
                edge_lon = longitude[:valid_rows, valid_cols - 1]
            edge_length = int(np.asarray(edge_lat).size)
            distance, valid_count = _minimum_domain_distance(
                edge_lon, edge_lat, target_grids
            )
            minimum = min(minimum, distance)
            # Any invalid/fill location on an omitted-neighbour edge is not a
            # proof of absence: the swath can become valid again.  Expand.
            # A one-pixel displacement guard also covers a current 250 m edge
            # whose immediately omitted neighbour could be ~180 m away.
            if valid_count != edge_length or distance <= (
                radius_m + adjacent_displacement_guard_m
            ):
                add.add(neighbor)
    return add, minimum, n_edges


def map_decoded_chunks_to_targets(
    selected: set[tuple[int, int]],
    decoded: Mapping[str, Mapping[tuple[int, int], np.ndarray]],
    target_grids: Mapping[str, TargetGrid],
    *,
    chunk_shape: tuple[int, int],
    array_shape: tuple[int, int] = FULL_SWATH_SHAPE,
    radius_m: float = RADIUS_OF_INFLUENCE_M,
) -> dict[str, dict[str, np.ndarray]]:
    """Nearest-neighbour map a full-resolution selected swath to target cells."""

    latitude_parts: list[np.ndarray] = []
    longitude_parts: list[np.ndarray] = []
    view_parts: list[np.ndarray] = []
    for coord in sorted(selected):
        for variable in GEOMETRY_VARIABLES:
            if coord not in decoded[variable]:
                raise ValueError(f"Selected chunk {coord} lacks {variable}")
        row_origin = coord[0] * chunk_shape[0]
        col_origin = coord[1] * chunk_shape[1]
        rows = min(chunk_shape[0], array_shape[0] - row_origin)
        cols = min(chunk_shape[1], array_shape[1] - col_origin)
        latitude = np.asarray(decoded["latitude"][coord][:rows, :cols], dtype=float)
        longitude = np.asarray(decoded["longitude"][coord][:rows, :cols], dtype=float)
        view = np.asarray(decoded["view_zenith"][coord][:rows, :cols], dtype=float)
        valid = _valid_geo(latitude, longitude) & np.isfinite(view) & (np.abs(view) <= 90)
        if valid.any():
            latitude_parts.append(latitude[valid])
            longitude_parts.append(longitude[valid])
            view_parts.append(np.abs(view[valid]).astype(np.float32))
    if not latitude_parts:
        raise ValueError("Selected full-resolution chunks contain no valid geometry")
    latitude = np.concatenate(latitude_parts)
    longitude = np.concatenate(longitude_parts)
    view = np.concatenate(view_parts)
    mapped: dict[str, dict[str, np.ndarray]] = {}
    for tile, grid in target_grids.items():
        transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        x, y = transformer.transform(longitude, latitude)
        xy = np.column_stack((x, y))
        finite = np.isfinite(xy).all(axis=1)
        source_view = view[finite]
        tree = cKDTree(xy[finite])
        distance, index = tree.query(
            np.column_stack((grid.x, grid.y)),
            k=1,
            distance_upper_bound=radius_m,
        )
        valid = np.isfinite(distance) & (index < len(source_view))
        target_index = np.flatnonzero(valid).astype(np.int32)
        mapped[tile] = {
            "target_index": target_index,
            "view_zenith_abs_deg": source_view[index[valid]].astype(np.float32),
            "source_distance_m": distance[valid].astype(np.float32),
        }
    return mapped


def write_scene_map_npz(
    path: str | Path,
    mapped: Mapping[str, Mapping[str, np.ndarray]],
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    for tile, values in sorted(mapped.items()):
        safe = re.sub(r"[^A-Za-z0-9]", "_", tile)
        arrays[f"{safe}__target_index"] = np.asarray(values["target_index"], dtype=np.int32)
        arrays[f"{safe}__view_zenith_abs_deg"] = np.asarray(
            values["view_zenith_abs_deg"], dtype=np.float32
        )
        arrays[f"{safe}__source_distance_m"] = np.asarray(
            values["source_distance_m"], dtype=np.float32
        )
    temporary = destination.with_name(f".{destination.name}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    temporary.replace(destination)


def read_scene_map_npz(path: str | Path) -> dict[str, dict[str, np.ndarray]]:
    output: dict[str, dict[str, np.ndarray]] = defaultdict(dict)
    with np.load(path, allow_pickle=False) as archive:
        for key in archive.files:
            tile, field_name = key.split("__", 1)
            output[tile][field_name] = archive[key]
    return {tile: dict(values) for tile, values in output.items()}


def summarize_geometry_passes(
    candidates: pd.DataFrame,
    scene_links: pd.DataFrame,
    scene_map_paths: Mapping[tuple[str, int, int], str | Path],
    target_grids: Mapping[str, Mapping[str, TargetGrid]],
    *,
    near_nadir_max_deg: float = NEAR_NADIR_MAX_DEG,
    minimum_coverage: float = MINIMUM_VIEW_COVERAGE,
    expected_candidates: int = EXPECTED_METADATA_CANDIDATES,
) -> pd.DataFrame:
    """Assemble scene maps with max-absolute overlap and summarize 942 passes."""

    grouped_links = {
        (str(city), int(orbit)): group
        for (city, orbit), group in scene_links.groupby(["city", "orbit"], sort=True)
    }
    rows: list[dict[str, Any]] = []
    for candidate in candidates.to_dict("records"):
        city = str(candidate["city"])
        orbit = int(candidate["orbit"])
        key = (city, orbit)
        if key not in grouped_links:
            raise ValueError(f"D0035 pass {key} has no scene link")
        combined = {
            tile: np.full(grid.size, np.nan, dtype=np.float32)
            for tile, grid in target_grids[city].items()
        }
        n_overlap = 0
        evidence: list[str] = []
        for link in grouped_links[key].sort_values("scene").itertuples(index=False):
            scene_key = (city, orbit, int(link.scene))
            if scene_key not in scene_map_paths:
                raise ValueError(f"D0035 pass {key} lacks definitive scene map {scene_key}")
            path = Path(scene_map_paths[scene_key])
            if not path.is_file():
                raise FileNotFoundError(path)
            evidence.append(f"{path.name}:{sha256_file(path)}:{path.stat().st_size}")
            scene_map = read_scene_map_npz(path)
            for tile, values in scene_map.items():
                if tile not in combined:
                    raise ValueError(f"Scene map contains unexpected target tile {city}/{tile}")
                indices = np.asarray(values["target_index"], dtype=np.int64)
                angles = np.asarray(values["view_zenith_abs_deg"], dtype=np.float32)
                distances = np.asarray(values["source_distance_m"], dtype=np.float32)
                if not (len(indices) == len(angles) == len(distances)):
                    raise ValueError("Scene-map arrays have inconsistent lengths")
                if len(indices) and (
                    indices.min() < 0 or indices.max() >= len(combined[tile])
                ):
                    raise ValueError("Scene map contains an out-of-range target index")
                if len(distances) and (not np.isfinite(distances).all() or (distances > RADIUS_OF_INFLUENCE_M).any()):
                    raise ValueError("Scene map violates the 210 m radius")
                existing = np.isfinite(combined[tile][indices])
                n_overlap += int(existing.sum())
                if len(indices):
                    old = combined[tile][indices]
                    combined[tile][indices] = np.where(
                        existing, np.maximum(old, angles), angles
                    )
        all_values = np.concatenate(
            [values[np.isfinite(values)] for values in combined.values()]
        )
        n_domain = sum(len(values) for values in combined.values())
        n_valid = int(len(all_values))
        coverage = n_valid / n_domain
        p95 = float(np.quantile(all_values, 0.95)) if n_valid else math.nan
        coverage_ok = bool(coverage >= minimum_coverage)
        angle_ok = bool(n_valid and p95 <= near_nadir_max_deg)
        if coverage_ok and angle_ok:
            status = "geometry_pass"
        elif not coverage_ok and not angle_ok:
            status = "coverage_and_angle_fail"
        elif not coverage_ok:
            status = "coverage_fail"
        else:
            status = "angle_fail"
        rows.append(
            {
                "city": city,
                "orbit": orbit,
                "acquisition_utc": pd.Timestamp(candidate["acquisition_utc"]).isoformat(),
                "year": int(pd.Timestamp(candidate["acquisition_utc"]).year),
                "metadata_candidate": True,
                "n_l1b_geo_scenes": int(len(grouped_links[key])),
                "n_domain_pixels": n_domain,
                "n_view_valid_pixels": n_valid,
                "view_valid_fraction": coverage,
                "view_zenith_abs_min_deg": float(np.min(all_values)) if n_valid else math.nan,
                "view_zenith_abs_median_deg": float(np.median(all_values)) if n_valid else math.nan,
                "view_zenith_abs_mean_deg": float(np.mean(all_values)) if n_valid else math.nan,
                "view_zenith_abs_p95_deg": p95,
                "view_zenith_abs_max_deg": float(np.max(all_values)) if n_valid else math.nan,
                "near_nadir_threshold_deg": float(near_nadir_max_deg),
                "minimum_view_coverage": float(minimum_coverage),
                "near_nadir": bool(coverage_ok and angle_ok),
                "n_overlapping_valid_pixels": n_overlap,
                "overlap_rule": "retain largest absolute finite L1B view zenith across scenes",
                "geometry_source": "ECO_L1B_GEO.002",
                "l1b_geometry_covered_cells": n_valid,
                "l1b_geometry_domain_cells": n_domain,
                "l1b_geometry_coverage_fraction": coverage,
                "l1b_view_zenith_abs_p95_deg": p95,
                "l1b_geometry_complete": True,
                "l1b_geometry_status": status,
                "quality_candidate_pre_cloud_l1b": bool(coverage_ok and angle_ok),
                "quality_candidate_pre_cloud": bool(coverage_ok and angle_ok),
                "quality_candidate_pre_cloud_l2t_invalid": bool(
                    candidate.get("quality_candidate_pre_cloud", False)
                ),
                # Compatibility aliases remain explicit in the remediation
                # artifact, while the canonical table columns are the L1B names.
                "geometry_resolution_status": status,
                "geometry_definitive": True,
                "quality_candidate_pre_cloud_geometry_only": bool(coverage_ok and angle_ok),
                "scene_map_set_sha256": sha256_strings(evidence),
                "decision_id": DECISION_ID,
            }
        )
    summary = pd.DataFrame(rows).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    ).reset_index(drop=True)
    if len(summary) != int(expected_candidates):
        raise ValueError(
            f"D0035 geometry summary does not contain exactly {expected_candidates} rows"
        )
    return summary


def build_geometry_validation(
    summary: pd.DataFrame,
    *,
    expected_candidates: int = EXPECTED_METADATA_CANDIDATES,
) -> dict[str, Any]:
    required = {
        "city",
        "orbit",
        "n_domain_pixels",
        "n_view_valid_pixels",
        "view_valid_fraction",
        "view_zenith_abs_p95_deg",
        "l1b_geometry_status",
        "l1b_geometry_complete",
        "quality_candidate_pre_cloud_l1b",
        "scene_map_set_sha256",
    }
    missing = sorted(required.difference(summary.columns))
    if missing:
        raise ValueError(f"Geometry summary lacks columns: {missing}")
    definitive = _bool_series(
        summary["l1b_geometry_complete"], name="l1b_geometry_complete"
    )
    resolved = int(definitive.sum())
    status_nonblank = summary["l1b_geometry_status"].astype(str).str.len().gt(0)
    hashes_valid = summary["scene_map_set_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}")
    unique = not summary.duplicated(["city", "orbit"]).any()
    counts_valid = (
        pd.to_numeric(summary["n_domain_pixels"], errors="coerce").gt(0)
        & pd.to_numeric(summary["n_view_valid_pixels"], errors="coerce").ge(0)
        & pd.to_numeric(summary["n_view_valid_pixels"], errors="coerce").le(
            pd.to_numeric(summary["n_domain_pixels"], errors="coerce")
        )
    )
    fraction = pd.to_numeric(summary["view_valid_fraction"], errors="coerce")
    ratio = pd.to_numeric(summary["n_view_valid_pixels"], errors="coerce") / pd.to_numeric(
        summary["n_domain_pixels"], errors="coerce"
    )
    fraction_equal = np.isclose(fraction, ratio, rtol=0, atol=1e-15)
    complete = bool(
        len(summary) == int(expected_candidates)
        and resolved == int(expected_candidates)
        and unique
        and status_nonblank.all()
        and hashes_valid.all()
        and counts_valid.all()
        and fraction_equal.all()
    )
    passing = int(
        _bool_series(
            summary["quality_candidate_pre_cloud_l1b"],
            name="quality_candidate_pre_cloud_l1b",
        ).sum()
    )
    return {
        "decision_id": DECISION_ID,
        "expected_metadata_candidates": int(expected_candidates),
        "resolved_geometry_candidate_count": resolved,
        # An explicit ``unresolved`` status is useful evidence, but it is not a
        # definitive geometry determination.  Count only sealed L1B results.
        "definitive_geometry_status_count": resolved,
        "unresolved_geometry_candidate_count": int(expected_candidates) - resolved,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": complete,
        "candidate_seal_geometry_only": complete,
        "candidate_view_mask_cloud_independent": complete,
        "view_gate_cloud_conditioned": False,
        "geometry_passing_candidate_count": passing,
        "scientific_gate_eligible": False,
        "gate_status": (
            "GEOMETRY_SEALED_AWAITING_EXHAUSTIVE_CLOUD"
            if complete
            else "STOP_D0035_INCOMPLETE_GEOMETRY"
        ),
        "canonical_status": (
            "GEOMETRY_SEALED_AWAITING_EXHAUSTIVE_CLOUD"
            if complete
            else "STOP_D0035_INCOMPLETE_GEOMETRY"
        ),
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }


__all__ = [
    "BOUNDARY_GUARD_DISTANCE_M",
    "ChunkDescriptor",
    "COLLECTION_VERSION",
    "DECISION_ID",
    "EXPECTED_CITY_SCENE_LINKS",
    "EXPECTED_METADATA_CANDIDATES",
    "EXPECTED_UNIQUE_SCENES",
    "FULL_SWATH_SHAPE",
    "GEOMETRY_VARIABLES",
    "G3_AZIMUTH_VARIABLES",
    "LOCATOR_MARGIN_PIXELS",
    "LOCATOR_STRIDE",
    "LOCATOR_INFLUENCE_M",
    "MAX_ADJACENT_SOURCE_DISPLACEMENT_M",
    "MINIMUM_VIEW_COVERAGE",
    "NEAR_NADIR_MAX_DEG",
    "NEAR_DOMAIN_PROOF_MODE",
    "NO_OVERLAP_LOCATOR_EXPECTED_CELLS",
    "NO_OVERLAP_LOCATOR_SHAPE",
    "NO_OVERLAP_LOCATOR_UNCERTAINTY_M",
    "NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS",
    "NO_OVERLAP_PROOF_MODE",
    "RADIUS_OF_INFLUENCE_M",
    "TargetGrid",
    "boundary_expansion_neighbors",
    "build_canonical_target_grids",
    "build_geometry_validation",
    "coalesce_chunk_ranges",
    "decode_chunk",
    "decode_selected_chunks",
    "frozen_geometry_targets",
    "finalize_initial_selection_proof",
    "initial_chunk_selection",
    "initial_chunk_selection_with_proof",
    "locator_indices",
    "map_decoded_chunks_to_targets",
    "normalize_geo_records",
    "parse_dmrpp_chunks",
    "parse_dmrpp_chunks_for_variables",
    "read_scene_map_npz",
    "resolve_latest_geo_scenes",
    "sha256_file",
    "sha256_strings",
    "summarize_geometry_passes",
    "write_scene_map_npz",
]
