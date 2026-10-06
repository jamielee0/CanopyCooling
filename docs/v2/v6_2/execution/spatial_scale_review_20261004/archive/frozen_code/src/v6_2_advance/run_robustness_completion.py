"""Complete frozen Phoenix registration and all-eleven common-cell diagnostics.

Publishes precision/support only. All coefficients and comparisons stay sealed.
The existing native-grid builder and estimator are reused without modification.
"""
from pathlib import Path
import json, sys, hashlib, datetime, gc
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from urban_cooling_v2.pooled_city_pass import fit_city_pass, public_precision
from urban_cooling_v2.pilot_native import ContextGrid, discover, build_pass
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from run_v6_2_pooled_pilot import digest, write_json

RUN = 'phoenix_robustness_20260923'
SHIFTS = [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]


def common_ids(frames):
    """Intersection of unique physical native-cell identities, independent of order."""
    if not frames:
        raise ValueError('No frames supplied')
    ids = []
    for frame in frames:
        if frame.cell_id.isna().any() or frame.cell_id.duplicated().any():
            raise ValueError('Native cell identities must be unique and nonmissing')
        ids.append(set(frame.cell_id))
    return sorted(set.intersection(*ids))


def restrict_ids(frame, ids):
    return frame.set_index('cell_id', drop=False).loc[ids].reset_index(drop=True)


def run():
    configs = [ROOT / 'docs/v2/v6_2/execution/phoenix_execution_manifest.json',
               ROOT / 'docs/v2/v6_2/execution/advance_20260921/phoenix_execution_manifest.json']
    old, added = [json.loads(p.read_text()) for p in configs]
    assert len(old['orbits']) == 5 and len(added['orbits']) == 6
    assert old['context_paths'] == added['context_paths'] and old['domain'] == added['domain']
    P = lambda n: guarded_output_path(ROOT, 'scientific', RUN + '/' + n)
    S = lambda n: guarded_output_path(ROOT, 'sealed', RUN + '/' + n)
    P('execution_freeze.json').parent.mkdir(parents=True, exist_ok=True)
    S('comparisons_SEALED.json').parent.mkdir(parents=True, exist_ok=True)
    S('comparisons_SEALED.json').parent.chmod(0o700)
    all_passes = [(c, orbit) for c in [old, added] for orbit in c['orbits']]
    source_cells = {orbit: guarded_output_path(ROOT, 'sealed', c['run_id'] + f'/{orbit}_paired_native_cells_SEALED.parquet') for c, orbit in all_passes}
    code = [Path(__file__), ROOT / 'src/urban_cooling_v2/pooled_city_pass.py',
            ROOT / 'src/urban_cooling_v2/pilot_native.py', ROOT / 'src/urban_cooling_v2/v6_2_output_boundary.py',
            ROOT / 'src/run_v6_2_d1d_stage1_precision.py']
    spec = {
        'run_id': RUN, 'city': 'phoenix', 'year': 2023,
        'registration_orbits': added['orbits'], 'common_cell_orbits': [o for _, o in all_passes],
        'registration_shifts_native_cells': SHIFTS, 'cell_metres': 70,
        'registration_rule': 'shift all context layers together; retain unchanged thermal outcomes; reproduce historical full-support checks and additionally compare on common support across five alignments',
        'common_cell_rule': 'exact unique native-cell intersection across all eleven 2023 Phoenix passes; refit all eleven, including original five',
        'paired_spaces': 'same cells, context, weights and bootstrap draws for LST and M',
        'bootstrap_replicates': 1000, 'seed_policy': 'reuse source manifest seed for each orbit',
        'baseline_validation': 'rebuilt unshifted registration frame must exactly equal cached original rows; baseline coefficients are unchanged',
        'publication': 'support, precision, numerical completion only; coefficients and baseline differences sealed',
        'no_new_passes_or_time_model': True, 'no_new_stability_cutoff': True,
        'prior_disclosure': 'Original ten and added six LST gradients previously disclosed; new robustness comparisons remain sealed; no global blindness claim.',
        'data_target': str((ROOT / 'data').resolve()),
        'source_manifests_sha256': {str(p.relative_to(ROOT)): digest(p) for p in configs},
        'code_sha256': {str(p.relative_to(ROOT)): digest(p) for p in code},
        'native_inputs_sha256': {str(p.relative_to(ROOT)): digest(p) for p in source_cells.values()},
    }
    freeze = P('execution_freeze.json')
    if freeze.exists():
        assert json.loads(freeze.read_text())['specification'] == json.loads(json.dumps(spec)), 'Frozen run changed'
    else:
        write_json(freeze, {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'specification': spec})
    rows, failures, comparisons = [], [], []
    def save_tables():
        pd.DataFrame(rows).to_csv(P('precision.csv'), index=False)
        write_json(P('nonestimable_variants.json'), failures)
        write_json(S('comparisons_SEALED.json'), comparisons)
        S('comparisons_SEALED.json').chmod(0o600)
    def fit_and_save(frame, config, orbit, variant):
        jp = P(f'{orbit}_{variant}_precision.json')
        dest = S(f'{orbit}_{variant}_SEALED.npz')
        comparison_path = S(f'{orbit}_{variant}_comparison_SEALED.json')
        if jp.exists() and dest.exists() and comparison_path.exists():
            rows.append(json.loads(jp.read_text()))
            comparisons.append(json.loads(comparison_path.read_text()))
            return
        try:
            fit = fit_city_pass(frame, bootstrap_replicates=1000, seed=config['seed'])
        except ValueError as e:
            failures.append({'orbit': orbit, 'variant': variant, 'status': 'NOT_ESTIMABLE', 'reason': str(e)})
            save_tables()
            return
        row = public_precision(fit, city='phoenix', pass_id=f'phoenix:{orbit}', variant=variant)
        row['source_run_id'] = config['run_id']
        np.savez_compressed(dest, coefficients=fit.coefficients, bootstrap_coefficients=fit.bootstrap_coefficients,
                            predictor_names=fit.predictor_names, outcome_names=fit.outcome_names,
                            block_labels=fit.block_labels, block_x_means=fit.block_x_means, block_y_means=fit.block_y_means)
        dest.chmod(0o600)
        # Read baseline effects programmatically only; never print or publish them.
        baseline_path = guarded_output_path(ROOT, 'sealed', config['run_id'] + f'/{orbit}_paired_primary_SEALED.npz')
        with np.load(baseline_path) as baseline:
            assert list(baseline['outcome_names']) == list(fit.outcome_names)
            before = baseline['coefficients'][0] * .1
        after = fit.coefficients[0] * .1
        comparison = {'orbit': orbit, 'variant': variant, 'outcomes': list(fit.outcome_names),
                      'baseline_signed_change_per_10pp': before.tolist(),
                      'variant_signed_change_per_10pp': after.tolist(),
                      'difference_from_baseline_per_10pp': (after-before).tolist(),
                      'same_nonzero_sign': ((np.sign(after) == np.sign(before)) & (after != 0) & (before != 0)).tolist(),
                      'interpretation': 'comparison stored for authorized review; no material-change threshold selected'}
        write_json(comparison_path, comparison); comparison_path.chmod(0o600)
        write_json(jp, row); rows.append(row); comparisons.append(comparison); save_tables()
        print(json.dumps({'orbit': orbit, 'variant': variant, 'cells': len(frame),
                          'SE_K_per_10pp': row['LST_K_SE_per_10pp'], 'bootstrap_estimable': row['bootstrap_estimable']}), flush=True)

    # Exact footprint check is available from existing inputs without rebuilding rasters.
    id_frames = [pd.read_parquet(p, columns=['cell_id']) for p in source_cells.values()]
    ids = common_ids(id_frames)
    retention = [{'orbit': orbit, 'original_cells': len(frame), 'common_cells': len(ids), 'retained_fraction': len(ids)/len(frame)}
                 for orbit, frame in zip(source_cells, id_frames)]
    pd.DataFrame(retention).to_csv(P('common_cell_retention.csv'), index=False)
    write_json(P('common_cell_support.json'), {'common_cells': len(ids), 'pass_count': 11,
        'identity_sha256': hashlib.sha256('\n'.join(ids).encode()).hexdigest(),
        'method': 'exact native cell_id intersection across all eleven current Phoenix passes',
        'cross_pass_LST_values_are_not_expected_equal': True})
    print(json.dumps({'stage': 'common_cell_support', 'common_cells': len(ids), 'passes': 11}), flush=True)
    del id_frames
    for config, orbit in all_passes:
        frame = pd.read_parquet(source_cells[orbit])
        fit_and_save(restrict_ids(frame, ids), config, orbit, 'common_cells_all11')
        del frame; gc.collect()

    # Reuse the original pixel builder and unchanged selected-pass inputs for shifts.
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely import make_valid
    import run_v6_2_d1d_stage1_precision as historical
    inputs = json.loads((ROOT / 'docs/v2/v6_2/execution/advance_20260921/new_run_inputs_sha256.json').read_text())['paths']
    for item in inputs:
        assert digest(ROOT / item['path']) == item['sha256'], 'Input checksum mismatch: ' + item['path']
    print(json.dumps({'stage': 'added_pass_input_checksums_verified', 'files': len(inputs)}), flush=True)
    g = gpd.GeoSeries([make_valid(shape(added['domain']))], crs=4326).to_crs(added['city_epsg']).iloc[0]
    a, t, crs, n = historical._building_presence_10m(g.bounds)
    ctx = ContextGrid(added['context_paths'], (a.astype(np.float32), t, crs))
    del a
    bundles = discover(added['thermal_root'], added['orbits'], added['emissivity_root'])
    registration_support = []
    for orbit in added['orbits']:
        print(json.dumps({'stage': 'build_registration_inputs', 'orbit': orbit}), flush=True)
        frames, ledger = build_pass([b for b in bundles if int(b['orbit']) == orbit], added['domain'], 'phoenix',
                                   added['city_epsg'], ctx, shifts=SHIFTS)
        pd.DataFrame(ledger).to_csv(P(f'{orbit}_native_ownership_audit.csv'), index=False)
        base = frames[(0, 0)]
        cached = pd.read_parquet(source_cells[orbit])
        columns = list(base.columns)
        pd.testing.assert_frame_equal(base[columns].sort_values('cell_id').reset_index(drop=True),
                                      cached[columns].sort_values('cell_id').reset_index(drop=True), check_exact=True)
        write_json(P(f'{orbit}_baseline_rebuild_validation.json'), {'orbit': orbit, 'status': 'EXACT_MATCH', 'cells': len(base), 'columns_compared': columns})
        del cached
        aligned_ids = common_ids(list(frames.values()))
        for (dx, dy), frame in frames.items():
            registration_support.append({'orbit': orbit, 'dx_cells': dx, 'dy_cells': dy,
                'full_support_cells': len(frame), 'common_across_alignments_cells': len(aligned_ids),
                'retained_fraction_of_unshifted': len(aligned_ids)/len(base)})
            if (dx, dy) != (0, 0):
                fit_and_save(frame, added, orbit, f'registration_dx{dx}_dy{dy}')
            fixed = restrict_ids(frame, aligned_ids)
            fixed_base = restrict_ids(base, aligned_ids)
            np.testing.assert_array_equal(fixed[['LST_K','M_W_m2','emissivity']].to_numpy(),
                                          fixed_base[['LST_K','M_W_m2','emissivity']].to_numpy())
            fit_and_save(fixed, added, orbit, f'registration_fixed_support_dx{dx}_dy{dy}')
            del fixed, fixed_base
        pd.DataFrame(registration_support).to_csv(P('registration_support.csv'), index=False)
        del frames, base; gc.collect()
    save_tables()
    expected = 11 + 6 * (4 + 5)
    write_json(P('completion.json'), {'completed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'requested_paired_fits': expected, 'completed_paired_fits': len(rows), 'nonestimable_variants': len(failures),
        'all_variants_accounted_for': len(rows)+len(failures) == expected,
        'registration_passes': 6, 'common_cell_passes': 11,
        'empirical_coefficients_and_comparisons': 'SEALED', 'time_model': 'NOT_RUN',
        'scientific_ruling': 'Numerical/support checks completed; effect-size robustness requires authorized review, no new cutoff or scale ruling.'})
    print(json.dumps({'stage': 'complete', 'paired_fits': len(rows), 'nonestimable': len(failures)}), flush=True)


if __name__ == '__main__':
    run()
