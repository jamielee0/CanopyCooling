"""Predict, verify the commit gate, then reveal seven archived cooling estimates."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/canopycooling_mpl_step2')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from .advisor_step2_models import fit_pass_model
from .advisor_step3_prediction import ORBITS,digest,predictions,verify_committed_bundle,temperature_estimate,coverage

R=Path(__file__).resolve().parents[2]
E=R/'docs/v2/v6_2/execution/advisor_step3_20261026'
P=R/'deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026'
B=P/'pre_access'
G=R/'outputs/v6_2/scientific/advisor_step3_20261026/git_checkout'
STEP1='deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/pass_inputs_23.csv'
STEP2='deliverables/Advisor_Step2_Models_2023_v6_2_20261026/model_inputs_2023.csv'
COEFS='deliverables/Advisor_Step2_Models_2023_v6_2_20261026/coefficients.csv'
PRECISION='deliverables/Sampling_Rebalance_v6_2_20260921/all18_pass_roles_and_precision.csv'
HISTORICAL='docs/v2/v6_2/rebalance_checksums_20260921.sha256'
SEALED='outputs/v6_2/sealed_coefficients/pooled_rebalance_20260921_phoenix'
CODE=['src/v6_2_advance/'+s for s in ['advisor_step2_models.py','advisor_step3_prediction.py','run_advisor_step3.py']]+['tests/v6_2_advance/test_advisor_step3_prediction.py']


def write(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')


def predict():
    if (E/'prediction_freeze.json').exists() or (E/'outcome_access_started.json').exists():
        raise ValueError('Do not replace the prospective prediction record')
    if json.loads((R/'docs/v2/v6_2/execution/advisor_step2_20261026/completion.json').read_text())['status']!='STEP2_COMPLETE_VERIFIED':
        raise ValueError('Step2 is not verified')
    prior=json.loads((R/'docs/v2/v6_2/execution/advisor_step2_20261026/completion.json').read_text())
    prior_freeze=json.loads((R/'docs/v2/v6_2/execution/advisor_step2_20261026/execution_freeze.json').read_text())
    for name in (STEP2,COEFS):
        if digest(R/name)!=prior['files'][name]:raise ValueError('Verified Step2 output changed')
    if digest(R/STEP1)!=prior_freeze['inputs'][STEP1]:raise ValueError('Step1 input changed')
    training=pd.read_csv(R/STEP2);training=training.loc[(training.city=='phoenix')&(training.population=='original')].copy()
    table=pd.read_csv(R/STEP1)
    held=table.loc[table.sample_role=='other_year_prediction_inputs_only'].copy()
    if held.cooling_K_per_10pp.notna().any():raise ValueError('Holdout was already filled')
    target=held[['city','orbit','local_date','acquisition_utc','apparent_solar_hour','after_noon','shortwave_W_m2','sin_solar_elevation','solar_elevation_deg']].copy().reset_index(drop=True)
    model,pred=predictions(training,target)
    co=pd.read_csv(R/COEFS);co=co.loc[(co.city=='phoenix')&(co.population=='original')&(co.predictor=='shortwave_W_m2')].set_index('term')
    np.testing.assert_allclose(model.params,co.loc[model.params.index,'estimate'],atol=1e-12,rtol=0)
    historical={name:h for h,name in [line.split('  ',1) for line in (R/HISTORICAL).read_text().splitlines() if line]}
    expected={}
    for orbit in sorted(ORBITS):
        for variant in ('paired_primary','spatial_8km'):
            name=f'{SEALED}/{orbit}_{variant}_SEALED.npz'
            if name not in historical or not (R/name).is_file():raise ValueError('Named archived estimate missing: '+name)
            expected[name]=historical[name] # Recorded checksum only; do not read estimate bytes yet.
    B.mkdir(parents=True,exist_ok=False)
    training.to_csv(B/'training_11.csv',index=False);target.to_csv(B/'target_inputs_7.csv',index=False);pred.to_csv(B/'predictions_7.csv',index=False)
    write(B/'training_model.json',{'formula':'cooling ~ shortwave_W_m2 + after_noon','population':'Phoenix original','n':11,
        'params':{k:float(v) for k,v in model.params.items()},'SE':{k:float(v) for k,v in model.bse.items()},
        'df_resid':int(model.df_resid),'residual_SD':float(np.sqrt(model.mse_resid)),
        'prediction_interval':'individual observation, 95%, obs_ci_lower/obs_ci_upper from summary_frame',
        'expectation':'Afternoon held-out points fall inside their intervals; refitted after_noon remains near zero or positive; no numerical near-zero threshold supplied.'})
    note=['# Step 3 prediction note — 26 October 2026','',f'Generated UTC: {datetime.now(timezone.utc).isoformat()}','',
      '**Written before opening the seven other-year cooling estimates. This note and its input/output bundle must be committed before outcome access.**','',
      'Use the original-population Phoenix shortwave model from Step 2, fitted to all eleven 2023 passes with equal pass weights. Cooling is K per +10 percentage points canopy; after_noon is 1 when apparent solar hour >12. The fitted equation is:', '',
      f"`predicted cooling = {model.params['Intercept']:.12f} + {model.params['shortwave_W_m2']:.12f} × shortwave_W_m2 + {model.params['after_noon']:.12f} × after_noon`",'',
      'The intervals below are individual 95% prediction intervals (`obs_ci_lower`, `obs_ci_upper`), including residual variance, with eight residual degrees of freedom. They are not confidence intervals for the mean and are not simultaneous seven-pass coverage intervals. Full precision is in `predictions_7.csv`.','',
      '| Orbit | Local date | Arm | Shortwave W/m² | Predicted cooling | 95% prediction interval | Outside training arm’s SW range? |',
      '|---|---|---|---:|---:|---|---|']
    for _,v in pred.iterrows():
        note.append(f"| {int(v.orbit)} | {v.local_date} | {'Afternoon' if v.after_noon else 'Morning'} | {v.shortwave_W_m2:.2f} | {v['mean']:.4f} | [{v.obs_ci_lower:.4f}, {v.obs_ci_upper:.4f}] | {'Yes' if v.outside_training_arm_shortwave_range else 'No'} |")
    note+=['','## Expectation recorded before access','',
      'If the afternoon decline is radiative, the three afternoon held-out estimates should fall inside their intervals, and the after-noon coefficient should stay near zero or positive when all seven are added. Report all seven point errors and interval checks, including failures. No numerical practical margin for “near zero” has been supplied; report the refit estimate, standard error and 95% interval without inventing a pass/fail margin. Interval inclusion alone will not prove the mechanism.','',
      'Two inputs extend beyond their training arm’s shortwave range (orbits 6281 and 33496). Retain both as requested and label extrapolation; do not change the prediction model or intervals after seeing outcomes. The existing models also retain alignment and canopy-vintage limitations.','',
      'After verifying the commit, read the seven checksum-bound existing temperature estimates, compare observed against these unchanged predictions, and refit the same unweighted model on all eighteen Phoenix original-population passes. No year/month controls, interactions, model search, new Stage 1 fits, new acquisitions or Step 4 work are added. Preserve the sixteen-pass 2023 main pilot as its original scope; the eighteen-pass refit is the advisor’s multiyear extension check.','',
      'The companion files contain the eleven training rows, seven nonthermal target rows, frozen model parameters and a standalone reproduction script. No seven-pass observed cooling values are present in this bundle.']
    (B/'prediction_note_20261026.md').write_text('\n'.join(note)+'\n')
    (B/'reproduce_predictions.py').write_text('''from pathlib import Path
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
p=Path(__file__).resolve().parent
train=pd.read_csv(p/'training_11.csv'); targets=pd.read_csv(p/'target_inputs_7.csv')
fit=smf.ols('cooling ~ shortwave_W_m2 + after_noon',data=train,missing='raise').fit()
actual=fit.get_prediction(targets).summary_frame(alpha=.05)
saved=pd.read_csv(p/'predictions_7.csv')
for key in actual:np.testing.assert_allclose(actual[key],saved[key],atol=1e-12,rtol=0)
print('All seven saved prediction means and intervals reproduced; no held-out outcomes read.')
''')
    inputs=[STEP1,STEP2,COEFS,PRECISION,HISTORICAL,'docs/v2/v6_2/execution/advisor_step3_20261026/scope.json']
    freeze={'date':'2026-10-26','created_utc':datetime.now(timezone.utc).isoformat(),
        'data_link_target':str((R/'data').resolve(strict=True)),
        'inputs':{n:digest(R/n) for n in inputs},'code':{n:digest(R/n) for n in CODE},
        'expected_archived_estimate_hashes_not_yet_read':expected,
        'prediction_bundle':{str(p.relative_to(R)):digest(p) for p in sorted(B.iterdir()) if p.is_file()},
        'other_year_outcomes_read':False,'n_target_morning':int((target.after_noon==0).sum()),'n_target_afternoon':int((target.after_noon==1).sum())}
    write(E/'prediction_freeze.json',freeze)
    print(pred[['orbit','after_noon','mean','obs_ci_lower','obs_ci_upper','outside_training_arm_shortwave_range']].to_string(index=False))


def check_freeze():
    f=json.loads((E/'prediction_freeze.json').read_text())
    if str((R/'data').resolve(strict=True))!=f['data_link_target']:raise ValueError('Data target changed')
    for name,h in {**f['inputs'],**f['code'],**f['prediction_bundle']}.items():
        if digest(R/name)!=h:raise ValueError('Frozen bytes changed: '+name)
    return f


def evaluate():
    f=check_freeze();receipt=json.loads((E/'prediction_commit_receipt.json').read_text())
    verify_committed_bundle(G,receipt['commit'],receipt['files'],R)
    if not set(f['prediction_bundle']).issubset(receipt['files']):raise ValueError('Prediction bundle not fully committed')
    if (E/'outcome_access_started.json').exists():raise ValueError('Preserve first outcome-access record; audit before rerunning')
    write(E/'outcome_access_started.json',{'utc':datetime.now(timezone.utc).isoformat(),'prediction_commit':receipt['commit'],
        'commit_verified_before_access':True,'authorized':'user request to do advisor Step3','allowed_files':list(f['expected_archived_estimate_hashes_not_yet_read']),
        'access':'read archived temperature canopy coefficient/draw entries only; no native cells or new Stage1 fit'})
    estimates={}
    for name,h in f['expected_archived_estimate_hashes_not_yet_read'].items():
        if digest(R/name)!=h:raise ValueError('Archived estimate checksum mismatch; ask before working around it')
        orbit=int(Path(name).name.split('_')[0]);variant='primary' if 'paired_primary' in name else '8km'
        estimates[(orbit,variant)]=temperature_estimate(R/name)
    pred=pd.read_csv(B/'predictions_7.csv');precision=pd.read_csv(R/PRECISION).set_index('orbit');comparisons=[]
    for _,v in pred.iterrows():
        primary,spatial=estimates[(int(v.orbit),'primary')],estimates[(int(v.orbit),'8km')]
        if abs(primary['cooling']-spatial['cooling'])>1e-10:raise ValueError('Original point differs by spatial grouping')
        if abs(spatial['SE']-precision.loc[v.orbit,'SE_8km_K_per_10pp'])>1e-10:raise ValueError('Archived spatial SE does not reproduce')
        comparisons.append({**v.to_dict(),'observed_cooling':primary['cooling'],'observed_spatial_q025_8km':spatial['q025'],
            'observed_spatial_q975_8km':spatial['q975'],'observed_spatial_SE_8km':spatial['SE'],'archived_8km_draws':spatial['draws'],
            **coverage(primary['cooling'],v['mean'],v.obs_ci_lower,v.obs_ci_upper)})
    compare=pd.DataFrame(comparisons);compare.to_csv(P/'observed_vs_predicted_7.csv',index=False)
    train=pd.read_csv(B/'training_11.csv');new=compare.copy();new['cooling']=new.observed_cooling
    new['q025']=new.observed_spatial_q025_8km;new['q975']=new.observed_spatial_q975_8km;new['population']='original'
    all18=pd.concat([train,new[train.columns]],ignore_index=True).sort_values('acquisition_utc').reset_index(drop=True)
    all18.to_csv(P/'refit_inputs_18.csv',index=False);model=fit_pass_model(all18,'shortwave_W_m2');ci=model.conf_int()
    co=[{'term':term,'estimate':float(model.params[term]),'standard_error':float(model.bse[term]),
         'ci95_low':float(ci.loc[term,0]),'ci95_high':float(ci.loc[term,1]),'n_passes':18,'df_resid':int(model.df_resid),
         'units':'K/+10pp per W/m2' if term=='shortwave_W_m2' else 'K/+10pp'} for term in model.params.index]
    pd.DataFrame(co).to_csv(P/'refit_coefficients.csv',index=False)
    residuals=all18[['orbit','local_date','cooling']].copy();residuals['fitted']=model.fittedvalues;residuals['residual']=model.resid
    residuals.to_csv(P/'refit_fitted_values.csv',index=False)
    diag={'n':18,'n_morning':int((all18.after_noon==0).sum()),'n_afternoon':int((all18.after_noon==1).sum()),
          'rank':int(model.model.rank),'df_resid':int(model.df_resid),'residual_SD':float(np.sqrt(model.mse_resid)),
          'R_squared':float(model.rsquared),'SSE':float(model.ssr)}
    write(P/'refit_diagnostics.json',diag)
    metrics={'prediction_commit':receipt['commit'],'held_out_passes':7,'inside_PI':int(compare.inside_prediction_interval.sum()),
      'afternoon_passes':int((compare.after_noon==1).sum()),
      'afternoon_inside_PI':int(compare.loc[compare.after_noon==1,'inside_prediction_interval'].sum()),
      'morning_inside_PI':int(compare.loc[compare.after_noon==0,'inside_prediction_interval'].sum()),
      'mean_error_observed_minus_predicted':float(compare.observed_minus_predicted.mean()),
      'RMSE':float(np.sqrt(np.mean(compare.observed_minus_predicted**2))),
      'after_noon':co[-1],'new_stage1_fits':0,'step4_started':False}
    write(P/'comparison_summary.json',metrics)
    fig,ax=plt.subplots(figsize=(8.5,7.5));colors={0:'#1b7198',1:'#bf5727'}
    for arm in (0,1):
        v=compare.loc[compare.after_noon==arm]
        ax.errorbar(v['mean'],v.observed_cooling,xerr=[v['mean']-v.obs_ci_lower,v.obs_ci_upper-v['mean']],
          yerr=[v.observed_cooling-v.observed_spatial_q025_8km,v.observed_spatial_q975_8km-v.observed_cooling],
          fmt='o' if arm==0 else '^',color=colors[arm],capsize=3,ms=8,lw=1.2,label=('Morning' if arm==0 else 'Afternoon')+f' (n={len(v)})')
        for _,z in v.iterrows():ax.annotate(str(int(z.orbit)),(z['mean'],z.observed_cooling),xytext=(6,8),textcoords='offset points',fontsize=9)
    low=min(compare.obs_ci_lower.min(),compare.observed_spatial_q025_8km.min())-.08
    high=max(compare.obs_ci_upper.max(),compare.observed_spatial_q975_8km.max())+.12
    ax.plot([low,high],[low,high],'--',color='#6b7280',lw=1,label='Observed = predicted')
    ax.set(xlim=(low,high),ylim=(low,high),xlabel='Predicted cooling from 2023 model (K/+10pp)',ylabel='Observed archived cooling (K/+10pp)')
    ax.set_aspect('equal',adjustable='box');ax.grid(alpha=.18);ax.legend(fontsize=9,loc='upper left')
    ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Phoenix: seven previously unopened passes',fontsize=16,fontweight='bold',y=.97)
    fig.text(.08,.035,'Horizontal bars: committed individual 95% prediction intervals.\nVertical bars: existing 95% spatial intervals (8 km). Labels: orbit.\nPredictions fixed before outcome access; the 18-pass refit does not change them.',fontsize=9)
    fig.tight_layout(rect=[0,.13,1,.94])
    for ext in ('png','pdf'):fig.savefig(P/('observed_vs_predicted.'+ext),dpi=180)
    plt.close(fig)
    write(E/'computed.json',{'status':'COMPUTED_PENDING_VERIFICATION','metrics':metrics,'diagnostics':diag,
          'archived_sources_unchanged':all(digest(R/n)==h for n,h in f['expected_archived_estimate_hashes_not_yet_read'].items())})
    print(json.dumps(metrics,indent=2));print(json.dumps(diag,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['predict','evaluate']);a=p.parse_args()
    {'predict':predict,'evaluate':evaluate}[a.action]()
