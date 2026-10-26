"""Independent matrix reconstruction and source reconciliation of Step 2."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t

R=Path(__file__).resolve().parents[2]
E=R/'docs/v2/v6_2/execution/advisor_step2_20261026'
P=R/'deliverables/Advisor_Step2_Models_2023_v6_2_20261026'


def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def verify():
    freeze=json.loads((E/'execution_freeze.json').read_text())
    for name,h in {**freeze['inputs'],**freeze['code']}.items():assert sha(R/name)==h,name
    rows=pd.read_csv(P/'model_inputs_2023.csv')
    coef=pd.read_csv(P/'coefficients.csv');diagnostics=pd.read_csv(P/'model_diagnostics.csv')
    ratios=pd.read_csv(P/'morning_afternoon_ratios.csv');fitted=pd.read_csv(P/'fitted_values_and_residuals.csv')
    source=pd.read_csv(R/'deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/pass_inputs_23.csv')
    common=pd.read_csv(R/'review/current/02_spatial_robustness/tables/common_footprint_comparisons.csv')
    assert len(rows)==27 and len(coef)==18 and len(diagnostics)==6 and len(ratios)==6 and len(fitted)==54
    assert rows[['city','orbit']].drop_duplicates().shape[0]==16
    assert rows.acquisition_utc.str.startswith('2023').all()
    assert source.loc[source.sample_role=='other_year_prediction_inputs_only','cooling_K_per_10pp'].isna().all()
    for _,r in rows.iterrows():
        s=source.loc[(source.city==r.city)&(source.orbit==r.orbit)].iloc[0]
        for k in ['shortwave_W_m2','sin_solar_elevation','after_noon','apparent_solar_hour']:assert r[k]==s[k]
        if r.population=='original':
            for k,sk in [('cooling','cooling_K_per_10pp'),('q025','cooling_q025_8km'),('q975','cooling_q975_8km')]:assert abs(r[k]-s[sk])<1e-12
        else:
            c=common.loc[(common.city==r.city)&(common.orbit==r.orbit)&(common.group_km==8)&(common.quantity=='temperature')].iloc[0]
            for k,sk in [('cooling','common_point'),('q025','common_q025'),('q975','common_q975')]:assert abs(r[k]-c[sk])<1e-12
    max_error=0
    for spec in freeze['models']:
        city,pop,x=spec['city'],spec['population'],spec['predictor']
        r=rows.loc[(rows.city==city)&(rows.population==pop)]
        assert r.orbit.tolist()==spec['orbits'] and len(r)==spec['n']
        X=np.column_stack([np.ones(len(r)),r[x],r.after_noon]);y=r.cooling.to_numpy()
        Q,U=np.linalg.qr(X,mode='reduced');b=np.linalg.solve(U,Q.T@y)
        residual=y-X@b;sse=residual@residual;df=len(y)-3;sd=np.sqrt(sse/df)
        inv=np.linalg.inv(U);se=np.sqrt(np.diag(inv@inv.T)*(sse/df));critical=t.ppf(.975,df)
        c=coef.loc[(coef.city==city)&(coef.population==pop)&(coef.predictor==x)].set_index('term').loc[['Intercept',x,'after_noon']]
        for observed,expected in [(c.estimate,b),(c.standard_error,se),(c.ci95_low,b-critical*se),(c.ci95_high,b+critical*se)]:
            np.testing.assert_allclose(observed,expected,atol=1e-10,rtol=1e-10)
            max_error=max(max_error,float(np.max(np.abs(observed-expected))))
        d=diagnostics.loc[(diagnostics.city==city)&(diagnostics.population==pop)&(diagnostics.predictor==x)].iloc[0]
        assert d.df_resid==df and d.design_rank==3 and abs(d.residual_SD_K_per_10pp-sd)<1e-12
        f=fitted.loc[(fitted.city==city)&(fitted.population==pop)&(fitted.predictor==x)]
        assert f.orbit.tolist()==r.orbit.tolist()
        np.testing.assert_allclose(f.fitted_cooling,X@b,atol=1e-12)
        np.testing.assert_allclose(f.residual,residual,atol=1e-12)
    for _,v in ratios.iterrows():
        r=rows.loc[(rows.city==v.city)&(rows.population==v.population)&(rows.after_noon==v.after_noon)]
        assert v.n_passes==len(r)
        assert abs(v.mean_cooling_over_shortwave-sum(float(a)/float(b) for a,b in zip(r.cooling,r.shortwave_W_m2))/len(r))<1e-12
    report={'status':'PASS','models_reconstructed_by_QR':6,'coefficient_and_SE_rows_verified':18,
      'ratio_groups_verified':6,'source_rows_reconciled':27,'max_coefficient_SE_or_CI_difference':max_error,
      'only_16_released_2023_passes':True,'other_year_outcomes_unopened':True,'verifier_sha256':sha(Path(__file__))}
    (E/'independent_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':verify()
