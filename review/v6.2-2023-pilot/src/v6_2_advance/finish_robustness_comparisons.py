"""Record matched-footprint registration differences, retaining all effects sealed."""
from pathlib import Path
import sys, json, datetime, hashlib
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from run_v6_2_pooled_pilot import digest, write_json

def run():
    run_id = 'phoenix_robustness_20260923'
    P = lambda n: guarded_output_path(ROOT, 'scientific', run_id+'/'+n)
    S = lambda n: guarded_output_path(ROOT, 'sealed', run_id+'/'+n)
    completed=json.loads(P('completion.json').read_text())
    assert completed['completed_paired_fits']==65 and completed['all_variants_accounted_for']
    orbits=json.loads(P('execution_freeze.json').read_text())['specification']['registration_orbits']
    dest=S('registration_matched_support_comparisons_SEALED.json')
    if dest.exists():
        raise FileExistsError('Matched-support comparison already exists; preserve frozen output')
    paths=sorted(S('placeholder_SEALED.json').parent.glob('*registration_fixed_support*_SEALED.npz'))
    assert len(paths)==30
    write_json(P('matched_support_comparison_freeze.json'),{
        'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'code_sha256':digest(Path(__file__)),
        'inputs_sha256':{p.name:digest(p) for p in paths},
        'rule':'shifted minus unshifted on identical per-pass cells; pair whole-block bootstrap draw indices after verifying block labels, array lengths and inherited seeds; no threshold ruling',
        'display_or_publish_empirical_values':False})
    rows=[];public=[]
    for orbit in orbits:
        with np.load(S(f'{orbit}_registration_fixed_support_dx0_dy0_SEALED.npz'), allow_pickle=True) as a:
            base_coef=a['coefficients'][0]*.1
            base_boot=a['bootstrap_coefficients'][:,0,:]*.1
            labels=a['block_labels'];outcomes=a['outcome_names']
        for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            variant=f'registration_fixed_support_dx{dx}_dy{dy}'
            with np.load(S(f'{orbit}_{variant}_SEALED.npz'), allow_pickle=True) as b:
                np.testing.assert_array_equal(labels,b['block_labels'])
                np.testing.assert_array_equal(outcomes,b['outcome_names'])
                before=json.loads(P(f'{orbit}_registration_fixed_support_dx0_dy0_precision.json').read_text())
                after=json.loads(P(f'{orbit}_{variant}_precision.json').read_text())
                assert before['seed']==after['seed'] and before['n_cells']==after['n_cells']
                assert base_boot.shape==b['bootstrap_coefficients'][:,0,:].shape
                delta=b['coefficients'][0]*.1-base_coef
                draws=b['bootstrap_coefficients'][:,0,:]*.1-base_boot
            valid=np.isfinite(draws).all(axis=1)
            rows.append({'orbit':orbit,'variant':variant,'outcomes':outcomes.tolist(),
                         'signed_difference_per_10pp':delta.tolist(),
                         'paired_difference_SE_per_10pp':np.std(draws[valid],axis=0,ddof=1).tolist(),
                         'paired_difference_q025_q975_per_10pp':np.quantile(draws[valid],[.025,.975],axis=0).tolist(),
                         'paired_estimable_draws':int(valid.sum())})
            public.append({'orbit':orbit,'variant':variant,'matched_cells':int(before['n_cells']),
                           'paired_estimable_draws':int(valid.sum()),'block_labels_and_seeds_match':True})
    write_json(dest,rows);dest.chmod(0o600)
    write_json(P('matched_support_comparison_validation.json'),{'comparison_count':len(rows),
               'publication':'validation counts only; effect differences and endpoints sealed','checks':public})
    print(json.dumps({'matched_support_comparisons_completed':len(rows),'all_effect_values':'SEALED'}))

if __name__=='__main__':run()
