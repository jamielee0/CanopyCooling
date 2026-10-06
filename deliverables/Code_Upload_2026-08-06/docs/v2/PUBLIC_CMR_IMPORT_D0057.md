# D0057 public-CMR metadata import

This is a metadata-only fallback for the time-of-day Task 2A preflight. It does
not authenticate to Earthdata, follow asset links, download a science file, or
open an LST/thermal array.

Save an official CMR response bundle at either frozen staging path:

- `data/raw/v2/ecostress/cmr_public_metadata_D0057/official_cmr_response_bundle.json`
- `data/raw/v2/ecostress/cmr_public_metadata_D0057/official_cmr_response_bundle.csv`

Then run:

```bash
PYTHONPATH=src /Users/jmlee/miniforge3/envs/urbanv2/bin/python \
  src/run_v2_task2_time_of_day.py \
  --import-public-cmr-metadata \
  data/raw/v2/ecostress/cmr_public_metadata_D0057/official_cmr_response_bundle.json
```

## JSON form

The importer accepts a normalized bundle or a list of raw CMR feed responses.
The normalized form is:

```json
{
  "collections": [
    {
      "short_name": "ECO_L2T_LSTE",
      "version_id": "002",
      "id": "C2076090826-LPCLOUD"
    }
  ],
  "granules": [
    {
      "collection_concept_id": "C2076090826-LPCLOUD",
      "producer_granule_id": "ECOv002_L2T_LSTE_00344_006_16SFB_20180728T223748_0712_01",
      "time_start": "2018-07-28T22:37:48.435Z",
      "orbit_calculated_spatial_domains": [
        {"start_orbit_number": "344", "stop_orbit_number": "344"}
      ],
      "granule_size": "10.0"
    }
  ]
}
```

All six frozen Collection-2 collection records are required. Granule records
must cover every response matching the generated CMR patterns. STARS matching
uses tile plus exact acquisition time and CMR orbit metadata; the other five
products use orbit, scene, tile, and acquisition time encoded in producer IDs.
Links may be present in raw CMR JSON, but the importer ignores and never follows
them.

## CSV form

CSV requires a `record_type` column with `collection` or `granule`. Use native
CMR field names. Collection rows require `short_name`, `version_id`, and `id`
(or `concept_id`). Granule rows require `collection_concept_id` and
`producer_granule_id`; STARS rows also require `time_start` and
`start_orbit_number`. `granule_size` is optional.

The resulting record binds the import file SHA-256, source scene-catalogue
SHA-256, config SHA-256, and all generated census tables. Any later change fails
preflight closed.
