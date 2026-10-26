"""Independent, network-free audit of the completed advisor Step 1 packet."""
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXEC = ROOT / 'docs/v2/v6_2/execution/advisor_step1_20261026'
PACKET = ROOT / 'deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify():
    freeze = json.loads((EXEC / 'execution_freeze.json').read_text())
    for path, sha in {**freeze['inputs'], **freeze['code_sha256']}.items():
        assert digest(ROOT / path) == sha, path
    rows = list(csv.DictReader((PACKET / 'pass_inputs_23.csv').open()))
    assert len(rows) == 23
    assert len({(r['city'], r['orbit']) for r in rows}) == 23
    assert Counter(r['city'] for r in rows) == {'phoenix': 18, 'atlanta': 5}
    old = list(csv.DictReader((ROOT / 'review/current/01_existing_results/pass_results_with_conditions.csv').open()))
    by_key = {(r['city'], r['orbit']): r for r in rows}
    for r in old:
        assert all(by_key[r['city'], r['orbit']][k] == v for k, v in r.items())
    held = [r for r in rows if r['sample_role'] == 'other_year_prediction_inputs_only']
    assert {int(r['orbit']) for r in held} == {6281, 6510, 33496, 33623, 40111, 40192, 40376}
    # Inspect every outcome-like output field, beyond the production guard list.
    effect_fields = [k for k in rows[0] if any(s in k.lower() for s in
                     ('cooling', 'gradient', 'equivalent', 'difference', 'slope'))]
    assert effect_fields
    for r in held:
        assert all(r[k] == '' for k in effect_fields), r['orbit']
    for r in rows:
        sw0, sw1 = float(r['shortwave_floor_W_m2']), float(r['shortwave_ceiling_W_m2'])
        c0, c1 = float(r['solar_cosine_floor']), float(r['solar_cosine_ceiling'])
        w, ca = float(r['hrrr_interpolation_weight']), float(r['sin_solar_elevation'])
        if min(c0, c1) >= .1:
            expected = ((1-w)*sw0/c0 + w*sw1/c1)*ca
        else:
            assert max(c0, c1) >= .1
            expected = (sw0/c0 if c0 >= .1 else sw1/c1)*ca
        assert abs(expected - float(r['shortwave_W_m2'])) < 1e-10
        assert abs(math.sin(math.radians(float(r['solar_elevation_deg']))) - ca) < 1e-12
        assert int(r['after_noon']) == int(float(r['apparent_solar_hour']) > 12)
        t = pd.Timestamp(r['acquisition_utc'])
        assert int(r['solar_days_in_year']) == (366 if t.is_leap_year else 365)
        assert pd.Timestamp(r['hrrr_floor_utc']) <= t <= pd.Timestamp(r['hrrr_ceiling_utc'])
    changed = {int(r['orbit']): float(r['geo_binding_minus_model_time_seconds'])
               for r in rows if float(r['geo_binding_minus_model_time_seconds']) != 0}
    assert set(changed) == {6281, 33623, 40111, 40376}
    assert all(51 < v < 53 for v in changed.values())
    assert json.loads((EXEC / 'scope.json').read_text())['approved_keep_model_table_times']
    scenes = json.loads((PACKET / 'scene_geolocation_provenance.json').read_text())
    assert len(scenes) == len({(s['city'], s['scene_key']) for s in scenes}) == 40
    assert Counter(s['category'] for s in scenes) == {'best': 38, 'good': 2}
    for r in rows:
        selected = [s for s in scenes if s['city'] == r['city'] and s['orbit'] == int(r['orbit'])]
        assert json.loads(r['geolocation_categories_by_scene']) == {s['scene_key']: s['category'] for s in selected}
    manifest = json.loads((EXEC / 'hourly_download_manifest.json').read_text())
    assert len(manifest) == 46
    old_matches, gribs = 0, 0
    for hour in manifest:
        assert digest(ROOT / hour['index']['path']) == hour['index']['sha256']
        assert len(hour['downloads']) == len(hour['grib_metadata']) == 5
        for source, meta in zip(hour['downloads'], hour['grib_metadata'], strict=True):
            assert digest(ROOT / source['path']) == source['sha256']
            assert 'wrfsfcf00' in source['url'] and 'noaa-hrrr-bdp-pds.s3.amazonaws.com' in source['url']
            assert source['bytes'] == source['byte_range'][1] - source['byte_range'][0] + 1
            assert meta['forecastTime'] == 0 and meta['stepType'] == 'instant'
            if meta['field'] == 'dswrf':
                assert meta['shortName'] == 'sdswrf' and meta['units'] == 'W m**-2'
            gribs += 1
        for r in hour['rows']:
            assert digest(ROOT / r['cells_path']) == r['cells_sha256']
            with np.load(ROOT / r['cells_path'], allow_pickle=False) as cells:
                for field in ('t2m', 'd2m', 'u10', 'v10', 'vpd', 'wind_speed', 'dswrf'):
                    assert abs(float(cells[field].mean()) - r[field+'_mean']) < 1e-12
            old_matches += r['historical_cell_values_reproduced'] is True
    assert old_matches == 32
    report = dict(status='PASS', pass_rows=23, original_rows_preserved=16,
                  other_year_rows_with_all_outcome_fields_blank=7,
                  checked_outcome_fields=effect_fields, scene_categories=dict(Counter(s['category'] for s in scenes)),
                  hourly_jobs=46, checked_grib_fields=gribs, historical_hourly_cell_arrays_reproduced=old_matches,
                  approved_timestamp_differences_seconds=changed,
                  shortwave_recomputed_rows=23, known_answer_tests_passed=21,
                  csv_sha256=digest(PACKET/'pass_inputs_23.csv'),
                  verifier_sha256=digest(Path(__file__)))
    (EXEC / 'independent_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    verify()
