"""Frozen, bounded execution of advisor Step 2 on already released pass rows."""
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/tmp/canopycooling_mpl_step2')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import statsmodels

from .advisor_step2_models import assemble_inputs, fit_pass_model, arm_ratios, PREDICTORS

ROOT=Path(__file__).resolve().parents[2]
EXEC=ROOT/'docs/v2/v6_2/execution/advisor_step2_20261026'
PACKET=ROOT/'deliverables/Advisor_Step2_Models_2023_v6_2_20261026'
TABLE='deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/pass_inputs_23.csv'
COMMON='review/current/02_spatial_robustness/tables/common_footprint_comparisons.csv'
CODE=['src/v6_2_advance/advisor_step2_models.py','src/v6_2_advance/run_advisor_step2.py',
      'tests/v6_2_advance/test_advisor_step2_models.py']


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')


def load():
    done=json.loads((ROOT/'docs/v2/v6_2/execution/advisor_step1_20261026/completion.json').read_text())
    if sha(ROOT/TABLE)!=done['csv_sha256']:raise ValueError('Step1 table checksum mismatch')
    # This is the public Step1 table, whose seven held-out outcome rows are blank.
    # Only authorized temperature columns are decoded from the public common table.
    common=pd.read_csv(ROOT/COMMON,usecols=['city','orbit','date','group_km','quantity','units',
        'original_point','common_point','common_q025','common_q975','requested','estimable','failed'])
    rows=assemble_inputs(pd.read_csv(ROOT/TABLE),common)
    return rows


def prepare():
    if (EXEC/'execution_freeze.json').exists():raise ValueError('Preserve existing freeze')
    scope=json.loads((EXEC/'scope.json').read_text())
    source=Path(scope['source_path'])
    if sha(source)!=scope['source_sha256']:raise ValueError('Advisor source changed')
    expected=json.loads((ROOT/'docs/v2/v6_2/execution/advisor_step1_20261026/scope.json').read_text())['data_link_target']
    if str((ROOT/'data').resolve(strict=True))!=expected:raise ValueError('Data link target changed')
    rows=load()
    record={'date':'2026-10-26','data_link_target':expected,
      'inputs':{p:sha(ROOT/p) for p in [TABLE,COMMON,'docs/v2/v6_2/execution/advisor_step2_20261026/scope.json']},
      'code':{p:sha(ROOT/p) for p in CODE},
      'versions':{'numpy':np.__version__,'pandas':pd.__version__,'scipy':scipy.__version__,'statsmodels':statsmodels.__version__},
      'models':[{'city':c,'population':p,'predictor':x,'orbits':r.orbit.astype(int).tolist(),
                 'n':len(r),'n_morning':int((r.after_noon==0).sum()),'n_afternoon':int((r.after_noon==1).sum())}
                for (c,p),r in rows.groupby(['city','population']) for x in PREDICTORS],
      'specification':{'intercept':True,'weights':'equal per pass; no inverse-variance weighting',
        'formula':'cooling ~ predictor + after_noon','after_noon':'apparent_solar_hour > 12',
        'coefficient_uncertainty':'ordinary homoskedastic OLS SE, t-based 95% interval, df=n-3',
        'residual_SD':'sqrt(SSE/(n-3))','ratios':'mean of individual cooling/shortwave ratios within arm',
        'intervals_on_figures':'existing 95% pass spatial intervals with 8 km grouping; not temporal regression uncertainty',
        'primary':'shortwave; sine-elevation and common-footprint repeats are prespecified sensitivities',
        'common_population_inputs':'reuse the same Step1 city-domain shortwave/solar geometry for the same pass',
        'figure_fit_lines':'OLS arm-specific lines only over each observed arm predictor range; no confidence ribbon',
        'no_new_stage1_fits':True,'other_year_outcomes_accessed':False,'step3_predictions':False}}
    write(EXEC/'execution_freeze.json',record)
    print(json.dumps({'status':'FROZEN','models':len(record['models']),'model_input_rows':len(rows)}))


def config():
    cfg=json.loads((EXEC/'execution_freeze.json').read_text())
    if str((ROOT/'data').resolve(strict=True))!=cfg['data_link_target']:raise ValueError('Data target changed')
    for p,h in {**cfg['inputs'],**cfg['code']}.items():
        if sha(ROOT/p)!=h:raise ValueError('Frozen input/code changed: '+p)
    return cfg


def plot_city(city,predictor,rows,models):
    pops=['original','common'] if city=='phoenix' else ['original']
    fig,axes=plt.subplots(1,len(pops),figsize=(12.5 if len(pops)==2 else 8,6.5),squeeze=False,sharey=True)
    colors={0:'#1b7198',1:'#bf5727'};markers={0:'o',1:'^'}
    for ax,pop in zip(axes[0],pops):
        r=rows.loc[(rows.city==city)&(rows.population==pop)]
        model=models[(city,pop,predictor)]
        for arm in (0,1):
            part=r.loc[r.after_noon==arm]
            label=('Morning' if arm==0 else 'Afternoon')+f' (n={len(part)})'
            ax.errorbar(part[predictor],part.cooling,yerr=[part.cooling-part.q025,part.q975-part.cooling],
                        fmt=markers[arm],color=colors[arm],ecolor=colors[arm],capsize=3,ms=7,lw=1.2,label=label)
            xx=np.linspace(part[predictor].min(),part[predictor].max(),100)
            yy=model.params['Intercept']+model.params[predictor]*xx+model.params['after_noon']*arm
            ax.plot(xx,yy,color=colors[arm],lw=1.7)
        ax.set_title(('Original pass populations' if pop=='original' else 'Common footprint')+f' · {len(r)} passes',fontsize=12)
        ax.set_xlabel('Incoming shortwave (W/m²)' if predictor==PREDICTORS[0] else 'Sine of sun elevation',fontsize=11)
        ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False);ax.legend(loc='best',fontsize=9,framealpha=.95)
        ax.text(.03,.97,f"After-noon term: {model.params['after_noon']:+.3f} ± {model.bse['after_noon']:.3f} SE\nResidual SD: {np.sqrt(model.mse_resid):.3f} K/+10pp",transform=ax.transAxes,va='top',fontsize=9,
                bbox={'facecolor':'white','edgecolor':'#d6dee5','alpha':.95})
    axes[0,0].set_ylabel('Canopy cooling (K per +10 percentage points)',fontsize=11)
    allcity=rows.loc[rows.city==city]
    lo,hi=allcity.q025.min(),allcity.q975.max();span=hi-lo
    for ax in axes[0]:ax.set_ylim(max(0,lo-.12*span),hi+.34*span)
    label='shortwave radiation' if predictor==PREDICTORS[0] else 'sun elevation'
    fig.suptitle(f'{city.title()}: canopy cooling and {label}',fontsize=16,fontweight='bold',y=.97)
    footer='Points and bars: existing pass cooling and 95% spatial intervals (8 km groups). Lines: unweighted OLS.'
    footer+='\n'+('Atlanta is descriptive: five dates and two residual degrees of freedom.' if city=='atlanta' else 'Common footprint changes the represented population; it uses the same city-domain radiation/solar inputs.')
    fig.text(.07,.035,footer,fontsize=9,color='#364451',va='bottom')
    fig.tight_layout(rect=[0,.12,1,.92])
    stem=f'{city}_'+('shortwave' if predictor==PREDICTORS[0] else 'sun_elevation')
    for ext in ('png','pdf'):fig.savefig(PACKET/(stem+'.'+ext),dpi=180)
    plt.close(fig)


def run():
    cfg=config(); rows=load();PACKET.mkdir(parents=True,exist_ok=True)
    models={};coefs=[];diagnostics=[];ratios=[];residuals=[]
    for (city,pop),r in rows.groupby(['city','population'],sort=True):
        for ratio in arm_ratios(r):ratios.append({'city':city,'population':pop,**ratio,'units':'(K/+10pp)/(W/m2)'})
        for predictor in PREDICTORS:
            m=fit_pass_model(r,predictor);models[(city,pop,predictor)]=m
            meta={'city':city,'population':pop,'predictor':predictor,'n_passes':len(r)}
            ci=m.conf_int()
            for term in m.params.index:
                units='K/+10pp'
                if term=='shortwave_W_m2':units+=' per W/m2'
                elif term=='sin_solar_elevation':units+=' per unit sine'
                coefs.append({**meta,'term':term,'estimate':float(m.params[term]),'standard_error':float(m.bse[term]),
                              'ci95_low':float(ci.loc[term,0]),'ci95_high':float(ci.loc[term,1]),'units':units,'df_resid':int(m.df_resid)})
            morning=r.loc[r.after_noon==0,predictor];afternoon=r.loc[r.after_noon==1,predictor]
            overlap_lo=max(morning.min(),afternoon.min());overlap_hi=min(morning.max(),afternoon.max())
            standardized=np.column_stack([np.ones(len(r)),(r[predictor]-r[predictor].mean())/r[predictor].std(ddof=0),
                                            (r.after_noon-r.after_noon.mean())/r.after_noon.std(ddof=0)])
            diagnostics.append({**meta,'n_morning':len(morning),'n_afternoon':len(afternoon),'design_rank':int(m.model.rank),
              'df_resid':int(m.df_resid),'residual_SD_K_per_10pp':float(np.sqrt(m.mse_resid)),'SSE':float(m.ssr),'r_squared':float(m.rsquared),
              'predictor_after_noon_correlation':float(r[predictor].corr(r.after_noon)),
              'standardized_design_condition_number':float(np.linalg.cond(standardized)),
              'morning_predictor_min':float(morning.min()),'morning_predictor_max':float(morning.max()),
              'afternoon_predictor_min':float(afternoon.min()),'afternoon_predictor_max':float(afternoon.max()),
              'arm_range_overlap':bool(overlap_lo<=overlap_hi),
              'arm_overlap_min':float(overlap_lo) if overlap_lo<=overlap_hi else None,
              'arm_overlap_max':float(overlap_hi) if overlap_lo<=overlap_hi else None,
              'interpretation':'descriptive; five passes' if city=='atlanta' else 'exploratory; eleven passes'})
            for i,index in enumerate(r.index):
                residuals.append({**meta,'orbit':int(r.loc[index,'orbit']),'local_date':r.loc[index,'local_date'],
                    'observed_cooling':float(r.loc[index,'cooling']),'fitted_cooling':float(m.fittedvalues.iloc[i]),'residual':float(m.resid.iloc[i])})
    rows.to_csv(PACKET/'model_inputs_2023.csv',index=False)
    for name,data in [('coefficients',coefs),('model_diagnostics',diagnostics),('morning_afternoon_ratios',ratios),('fitted_values_and_residuals',residuals)]:
        pd.DataFrame(data).to_csv(PACKET/(name+'.csv'),index=False)
    for city in ('phoenix','atlanta'):
        for predictor in PREDICTORS:plot_city(city,predictor,rows,models)
    write(EXEC/'completion.json',{'status':'STEP2_MODELS_COMPUTED_PENDING_INDEPENDENT_AND_VISUAL_CHECKS','models':6,
        'coefficient_rows':len(coefs),'ratio_rows':len(ratios),'unique_2023_passes':16,'common_footprint_passes':11,
        'new_stage1_fits':0,'other_year_outcomes_opened':False,'step3_predictions_computed':False,
        'files':{str(p.relative_to(ROOT)):sha(p) for p in sorted(PACKET.iterdir()) if p.is_file()}})
    print(pd.DataFrame(coefs).loc[lambda d:d.term=='after_noon'].to_string(index=False))
    print(pd.DataFrame(diagnostics)[['city','population','predictor','residual_SD_K_per_10pp','df_resid','arm_range_overlap']].to_string(index=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run']);args=parser.parse_args()
    {'prepare':prepare,'run':run}[args.action]()
