"""Independent numerical and chronological verification of advisor Step 3."""
from pathlib import Path
import json
import subprocess
import numpy as np
import pandas as pd
from scipy.stats import t
from .advisor_step3_prediction import digest,verify_committed_bundle

R=Path(__file__).resolve().parents[2];E=R/'docs/v2/v6_2/execution/advisor_step3_20261026'
P=R/'deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026';B=P/'pre_access'


def verify():
    f=json.loads((E/'prediction_freeze.json').read_text());receipt=json.loads((E/'prediction_commit_receipt.json').read_text())
    gate=json.loads((E/'outcome_access_started.json').read_text())
    verify_committed_bundle(Path(receipt['checkout']),receipt['commit'],receipt['files'],R)
    assert pd.Timestamp(f['created_utc'])<=pd.Timestamp(receipt['commit_time'])<=pd.Timestamp(gate['utc'])
    for name,h in {**f['inputs'],**f['code'],**f['prediction_bundle'],**f['expected_archived_estimate_hashes_not_yet_read']}.items():assert digest(R/name)==h,name
    pred=pd.read_csv(B/'predictions_7.csv');compare=pd.read_csv(P/'observed_vs_predicted_7.csv')
    for col in pred:
        if pd.api.types.is_numeric_dtype(pred[col]):np.testing.assert_allclose(compare[col],pred[col],atol=0,rtol=0)
        else:assert compare[col].tolist()==pred[col].tolist()
    for _,v in compare.iterrows():
        name=next(n for n in f['expected_archived_estimate_hashes_not_yet_read'] if n.endswith(f'/{int(v.orbit)}_paired_primary_SEALED.npz'))
        with np.load(R/name,allow_pickle=False) as z:
            i=list(z['predictor_names']).index('canopy_fraction');j=list(z['outcome_names']).index('LST_K')
            expected=-float(z['coefficients'][i,j])/10
        assert abs(v.observed_cooling-expected)<1e-12
        assert abs(v.observed_minus_predicted-(expected-v['mean']))<1e-12
        assert bool(v.inside_prediction_interval)==bool(v.obs_ci_lower<=expected<=v.obs_ci_upper)
    train=pd.read_csv(B/'training_11.csv');all18=pd.read_csv(P/'refit_inputs_18.csv')
    assert len(all18)==18 and all18.orbit.nunique()==18 and all18.local_date.nunique()==18
    for _,v in train.iterrows():
        s=all18.loc[all18.orbit==v.orbit].iloc[0]
        for k in train:
            if isinstance(v[k],(float,int,np.number)):assert abs(v[k]-s[k])<1e-12
            else:assert v[k]==s[k]
    for _,v in compare.iterrows():
        s=all18.loc[all18.orbit==v.orbit].iloc[0]
        for k in ['shortwave_W_m2','after_noon','acquisition_utc','local_date']:assert s[k]==v[k]
        assert abs(s.cooling-v.observed_cooling)<1e-12
    X=np.column_stack([np.ones(18),all18.shortwave_W_m2,all18.after_noon]);y=all18.cooling.to_numpy()
    Q,U=np.linalg.qr(X);coef=np.linalg.solve(U,Q.T@y);res=y-X@coef;sse=res@res;sd=np.sqrt(sse/15)
    inv=np.linalg.inv(U);se=np.sqrt(np.diag(inv@inv.T)*sd**2);crit=t.ppf(.975,15)
    out=pd.read_csv(P/'refit_coefficients.csv').set_index('term').loc[['Intercept','shortwave_W_m2','after_noon']]
    for observed,expected in [(out.estimate,coef),(out.standard_error,se),(out.ci95_low,coef-crit*se),(out.ci95_high,coef+crit*se)]:np.testing.assert_allclose(observed,expected,atol=1e-12,rtol=0)
    diag=json.loads((P/'refit_diagnostics.json').read_text());assert abs(diag['residual_SD']-sd)<1e-12 and diag['df_resid']==15
    residual=pd.read_csv(P/'refit_fitted_values.csv');np.testing.assert_allclose(residual.residual,res,atol=1e-12,rtol=0)
    metrics=json.loads((P/'comparison_summary.json').read_text())
    assert metrics['inside_PI']==int(compare.inside_prediction_interval.sum())==7
    assert metrics['afternoon_inside_PI']==int(compare.loc[compare.after_noon==1,'inside_prediction_interval'].sum())==3
    assert abs(metrics['RMSE']-np.sqrt(np.mean(compare.observed_minus_predicted**2)))<1e-12
    assert abs(metrics['mean_error_observed_minus_predicted']-compare.observed_minus_predicted.mean())<1e-12
    report={'status':'PASS','prediction_commit':receipt['commit'],'prediction_commit_precedes_outcome_access':True,
        'committed_prediction_bytes_unchanged':True,'archived_estimate_hashes_unchanged':14,
        'heldout_observed_points_and_errors_reconciled':7,'refit_coefficients_SEs_intervals_residuals_reconstructed_by_QR':True,
        'original_11_training_rows_preserved':True,'all18_unique_dates':True,'raw_thermal_cells_read':False,
        'verifier_sha256':digest(Path(__file__))}
    (E/'independent_verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':verify()
