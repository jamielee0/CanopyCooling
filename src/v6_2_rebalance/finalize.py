"""Publish nonthermal sampling and precision evidence; keep gradients sealed."""
from pathlib import Path
import sys,json,hashlib,datetime,shutil
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path,validate
sys.path.insert(0,str(Path(__file__).parent))
from sampling_design import balanced_weights
OUT=ROOT/'docs/v2/v6_2/execution/rebalance_20260921'
PKG=ROOT/'deliverables/Sampling_Rebalance_v6_2_20260921';PKG.mkdir(parents=True,exist_ok=True)
RUN='pooled_rebalance_20260921_phoenix'
pub=ROOT/'outputs/v6_2/scientific'/RUN
completion=json.loads((pub/'completion.json').read_text())
assert completion['primary_fits']==7 and completion['fits']==28 and not completion['failures'],completion
selected=pd.read_csv(OUT/'balanced12_selection.csv');current=pd.read_csv(OUT/'current11_rebalanced_roles.csv')
archive=pd.read_csv(OUT/'archive_pass_audit.csv');cloud=pd.read_csv(OUT/'cloud_screen_summary.csv')
freeze=json.loads((OUT/'thermal_batch_selection_freeze.json').read_text())
parts=[]
for run in ['pooled_pilot_20260919_phoenix','pooled_extension_20260921_phoenix',RUN]:
    q=pd.read_csv(ROOT/'outputs/v6_2/scientific'/run/'precision.csv');q=q[q.variant.eq('paired_primary')].copy();q['orbit']=q.pass_id.str.split(':').str[-1].astype(int);q['run_id']=run
    stress=ROOT/'outputs/v6_2/scientific'/run/'spatial_stress_precision.csv'
    q8=pd.read_csv(stress if stress.exists() else ROOT/'outputs/v6_2/scientific'/run/'precision.csv');q8=q8[q8.variant.eq('spatial_8km')].copy();q8['orbit']=q8.pass_id.str.split(':').str[-1].astype(int)
    q=q.merge(q8[['orbit','LST_K_SE_per_10pp','bootstrap_failed']].rename(columns={'LST_K_SE_per_10pp':'SE_8km_K_per_10pp','bootstrap_failed':'bootstrap_failed_8km'}),on='orbit',validate='one_to_one')
    parts.append(q[['orbit','run_id','n_cells','n_blocks','contributing_blocks','within_block_Sxx','maximum_block_information_share','LST_K_SE_per_10pp','SE_8km_K_per_10pp','M_W_m2_SE_per_10pp','bootstrap_failed','bootstrap_failed_8km']])
precision=pd.concat(parts,ignore_index=True);assert len(precision)==18 and not precision.orbit.duplicated().any()
all18=archive[archive.orbit.isin(precision.orbit)].merge(precision,on='orbit',validate='one_to_one')
all18=all18.merge(selected[['orbit','balanced_arm_weight','balanced_design_weight']],on='orbit',how='left');all18[['balanced_arm_weight','balanced_design_weight']]=all18[['balanced_arm_weight','balanced_design_weight']].fillna(0)
all18['sampling_role']=np.select([all18.balanced_arm_weight.gt(0),all18.year_month.isin(selected.year_month)],['balanced_endpoint_subset','supported_season_middle_time'],default='descriptive_unmatched_season')
all18['new_in_this_run']=all18.orbit.isin(freeze['selected_new_orbits'])
all18['gradient_release']='previously_disclosed' ;all18.loc[all18.new_in_this_run,'gradient_release']='SEALED'
all18.to_csv(PKG/'all18_pass_roles_and_precision.csv',index=False)
end=all18[all18.balanced_arm_weight.gt(0)].copy();end.to_csv(PKG/'balanced12_passes.csv',index=False)
new=all18[all18.new_in_this_run].copy();new.to_csv(PKG/'new7_passes_and_precision.csv',index=False)

# Verify paired response physics and native-cell IDs, without opening coefficient
# arrays. Joint cell support is calculated independently within each year-month.
cell_support=[];checks=[]
for ym,g in end.groupby('year_month'):
    frames={}
    for r in g.itertuples(index=False):
        path=ROOT/'outputs/v6_2/sealed_coefficients'/r.run_id/f'{r.orbit}_paired_native_cells_SEALED.parquet'
        f=pd.read_parquet(path,columns=['cell_id','block','canopy_fraction','LST_K','emissivity','M_W_m2'])
        assert not f.cell_id.duplicated().any(),r.orbit
        m=f.emissivity.to_numpy()*5.670374419e-8*f.LST_K.to_numpy()**4
        assert np.allclose(m,f.M_W_m2,rtol=1e-12,atol=1e-8),r.orbit
        assert f.canopy_fraction.between(0,1).all()
        checks.append({'orbit':int(r.orbit),'unique_native_cell_ids':True,'emitted_energy_identity':True,'native_cells':len(f)})
        frames[r.orbit]=f[['cell_id','block','canopy_fraction']]
    common=set.intersection(*(set(f.cell_id) for f in frames.values()))
    for orbit,f in frames.items():
        q=f[f.cell_id.isin(common)];gr=q.groupby('block').canopy_fraction
        sxx=float(((q.canopy_fraction-gr.transform('mean'))**2).sum())
        cell_support.append({'year_month':ym,'orbit':int(orbit),'native_cells':len(f),'common_native_cells_all_stratum_passes':len(common),'retained_fraction_on_common_cells':len(common)/len(f),'contributing_common_blocks':int(gr.var().fillna(0).gt(0).sum()),'common_within_block_Sxx':sxx})
joint=pd.DataFrame(cell_support);joint.to_csv(PKG/'within_stratum_native_cell_support.csv',index=False)

# Synthetic known-answer scenarios use metadata only, not empirical gradients.
sim=[]
for label,d in [('original_11_endpoint_windows',all18[~all18.new_in_this_run & all18.time_window.isin(['morning','afternoon'])]),('balanced_2023_endpoints',current[current.balanced_arm_weight.gt(0)]),('balanced_12_endpoints',end)]:
    d=d.copy();day=pd.to_datetime(d.local_date).dt.day.to_numpy();year=d.year.to_numpy();month=d.month.to_numpy();h=d.solar_hour.to_numpy()
    is_balanced=label!='original_11_endpoint_windows'
    weights=d.balanced_arm_weight.to_numpy() if is_balanced else np.array([1/(d.time_window==a).sum() for a in d.time_window])
    for name,within_day in [('season_and_year_only',0.0),('additional_uncontrolled_day_of_month_trend',0.005)]:
        fake=(month-6)*0.4+(year-2023)*0.1+within_day*(day-15)
        sign=np.where(d.time_window.eq('afternoon'),1,-1)
        contrast=float(np.sum(sign*weights*fake))
        # Independent illustrative pass noise; this is bias diagnosis, not power.
        rng=np.random.default_rng(20260921);rep=contrast+(rng.normal(0,.03,(10000,len(d)))*(sign*weights)).sum(axis=1)
        sim.append({'DATA_KIND':'SYNTHETIC_DATA','design':label,'scenario':name,'true_time_effect_K_per_10pp':0,'deterministic_artificial_window_contrast':contrast,'simulation_mean':float(rep.mean()),'simulation_SD':float(rep.std(ddof=1)),'replicates':10000,'assumed_independent_pass_noise_SD':.03})
sp=guarded_output_path(ROOT,'synthetic','rebalance_20260921/SYNTHETIC_DATA_balance_bias.csv');sp.parent.mkdir(parents=True,exist_ok=True);pd.DataFrame(sim).to_csv(sp,index=False)
assert all(abs(r['deterministic_artificial_window_contrast'])<1e-12 for r in sim if r['design'].startswith('balanced') and r['scenario']=='season_and_year_only')

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(13.5,6),gridspec_kw={'width_ratios':[1,1.25]})
q=all18[~all18.new_in_this_run];colors={'balanced_endpoint_subset':'#167a87','supported_season_middle_time':'#777e87','descriptive_unmatched_season':'#d18b32'}
for role,g in q.groupby('sampling_role'):
    axes[0].scatter(g.solar_hour,g.month,s=85,color=colors[role],label=role)
    for r in g.itertuples():axes[0].annotate(r.local_date[5:],(r.solar_hour,r.month),xytext=(0,9),textcoords='offset points',ha='center',fontsize=8)
axes[0].set_yticks([6,7,8,9],['June','July','August','September']);axes[0].invert_yaxis();axes[0].set_ylim(9.5,5.5);axes[0].set_xlim(9.3,17.7);axes[0].set_title('Original 11: retain every result',loc='left',weight='bold');axes[0].set_xlabel('Apparent local solar time (hours)')
levels=sorted(end.year_month.unique());lookup={v:i for i,v in enumerate(levels)}
for r in end.itertuples():
    y=lookup[r.year_month];axes[1].scatter(r.solar_hour,y,s=90,marker='s' if r.new_in_this_run else 'o',color='#167a87',edgecolor='white',zorder=3)
    axes[1].annotate(r.local_date[5:],(r.solar_hour,y),xytext=(0,10),textcoords='offset points',ha='center',fontsize=8)
axes[1].set_yticks(range(len(levels)),[pd.Timestamp(x+'-01').strftime('%b %Y') for x in levels]);axes[1].set_ylim(len(levels)-.5,-.5);axes[1].set_xlim(9.3,17.7);axes[1].set_title('Balanced comparison: 12 passes, 5 year-months',loc='left',weight='bold');axes[1].set_xlabel('Apparent local solar time (hours)')
for ax in axes:
    ax.axvspan(9.5,11.5,color='#167a87',alpha=.07);ax.axvspan(15,18,color='#167a87',alpha=.07);ax.grid(axis='y',alpha=.16);ax.axvline(10.5,color='#9aa0a6',ls=':',lw=1);ax.axvline(16,color='#9aa0a6',ls=':',lw=1)
from matplotlib.lines import Line2D
fig.legend(handles=[Line2D([],[],ls='',marker='o',color='#167a87',label='Existing endpoint pass'),Line2D([],[],ls='',marker='s',color='#167a87',label='New endpoint pass'),Line2D([],[],ls='',marker='o',color='#777e87',label='Middle time: shape/context'),Line2D([],[],ls='',marker='o',color='#d18b32',label='Unmatched season: descriptive')],loc='lower center',ncol=2,bbox_to_anchor=(.5,.055),frameon=False)
fig.suptitle('Phoenix sampling rebalanced within the same year and month',x=.075,y=.96,ha='left',weight='bold',fontsize=16)
fig.text(.075,.025,'Both arms receive identical year-month weights. Day-to-day weather and within-month date differences remain.',fontsize=10,color='#4b5563')
fig.subplots_adjust(left=.075,right=.98,top=.82,bottom=.25,wspace=.32)
fig.savefig(PKG/'sampling_balance.png',dpi=170);fig.savefig(PKG/'sampling_balance.pdf');plt.close(fig)

def hm(x):
    n=int(round(x*60));return f'{n//60:02d}:{n%60:02d}'
def table(d):
    rows=['| Orbit | Phoenix date | Clock (MST) | Solar time | 1 km SE | 8 km SE |','|---|---|---|---|---:|---:|']
    for r in d.itertuples():
        dt=pd.Timestamp(r.acquisition_utc).tz_convert('America/Phoenix');clock=(dt+pd.Timedelta(seconds=30)).strftime('%H:%M')
        rows.append(f'| {r.orbit:05d} | {r.local_date} | {clock} | {hm(r.solar_hour)} | {r.LST_K_SE_per_10pp:.4f} | {r.SE_8km_K_per_10pp:.4f} |')
    return '\n'.join(rows)

newprec=pd.read_csv(pub/'precision.csv');fails=int(newprec.bootstrap_failed.sum())
summary={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'processed_phoenix_passes':18,'new_phoenix_passes':7,'balanced_endpoint_passes':12,'matched_year_month_strata':5,'new_paired_fits':28,'requested_new_bootstrap_draws':28000,'failed_new_bootstrap_draws':fails,'new_primary_SE_range':new.LST_K_SE_per_10pp.agg(['min','max']).to_dict(),'new_8km_SE_range':new.SE_8km_K_per_10pp.agg(['min','max']).to_dict(),'common_cell_retention_range':joint.retained_fraction_on_common_cells.agg(['min','max']).to_dict(),'new_gradients_disclosed':False,'new_time_model_fitted':False,'all_eleven_preserved':True,'native_cell_checks':checks,'output_boundary_errors':validate(ROOT)}
assert not summary['output_boundary_errors']
(PKG/'verification.json').write_text(json.dumps(summary,indent=2)+'\n')
doc=f'''# Phoenix sampling rebalance — v6.2, 21 September 2026

The bounded expansion is complete: **18 Phoenix passes have paired Stage 1 fits**, including seven new acquisitions. **Twelve passes form a balanced morning/afternoon subset across five year-months.** Atlanta remains at five. The original eleven Phoenix results and all historical packages are preserved. New gradients remain sealed; this package reports sample design and precision.

![Sampling before and after](sampling_balance.png)

## Why the design changed

The complete cached Collection 2 catalogue contains 547 distinct Phoenix June–September orbit acquisitions in 2019–2025, after local-date filtering and numeric revision deduplication. In 2023 it contains 73 summer acquisitions but **zero July and zero September morning acquisitions in 09:30–11:30 apparent solar time**, before any geometry/cloud exclusion. Those gaps cannot be repaired by searching harder within 2023 or by weighting. Other times remain in the archive ledger.

The broader archive has a few July/September morning opportunities in other years, but the inherited verified geometry frame supplies no supported morning/afternoon pair for those year-months. Unknown geometry remains unresolved, not unsuitable. The present sample therefore supports a June/August comparison; it does not establish a June–September-wide diurnal pattern.

## What was added

The seven additions were frozen using dates, definitive geometry and cloud masks before downloading their thermal layers. Dates and clocks below are Phoenix local civil time (MST, UTC−7); solar time includes longitude and the equation of time. Times are rounded to the nearest minute. This audit uses the earliest scene timestamp in each orbit; some earlier tables used a later representative scene, so displayed times can differ by about one minute without changing the pass identity. Standard errors are K per +10 percentage points canopy, not cooling gradients.

{table(new)}

The same block-intercept canopy model was fitted in temperature and emitted-energy space, with matching cells/controls and 1,000 paired bootstrap draws at each 1/2/4/8 km grouping. All seven primary fits completed; {fails} of 28,000 requested bootstrap draws were rank failures. New primary SEs range {new.LST_K_SE_per_10pp.min():.4f}–{new.LST_K_SE_per_10pp.max():.4f}; 8 km SEs range {new.SE_8km_K_per_10pp.min():.4f}–{new.SE_8km_K_per_10pp.max():.4f}. Precision does not establish the time contrast or eliminate spatial dependence.

## How the passes are used

- **Balanced endpoint subset: 12 passes.** August 2019 (2), June 2023 (2), August 2023 (3), June 2024 (2), August 2025 (3). Each year-month gets 20% of each arm's weight, divided equally among its available passes. An extra morning pass therefore does not give that season more influence. Both arms have 40% June and 60% August weight. All selected passes are retained.
- **Middle-time context: 3 passes.** 15 June, 19 June and 15 August 2023 remain available to describe the curve within supported months. They have zero weight in the endpoint-window mean comparison.
- **Unmatched-season description: 3 passes.** 29 July, 21 September and 25 September 2023 remain on the all-pass descriptive plot and in the archive. They have zero weight in this matched-season endpoint comparison. No files or results were deleted.

For S=5 supported year-month strata, endpoint pass i in arm a and stratum s has **arm weight 1/(S × n_sa)**. The weighted afternoon mean minus weighted morning mean defines a window contrast. Its weight is the same in the LST and emitted-energy analyses. The companion design weight is arm weight/2 and sums to one over all twelve passes. The complete manifest and roles are in [all18_pass_roles_and_precision.csv](all18_pass_roles_and_precision.csv).

**This window comparison does not equal an exact 10:30-versus-16:00 prediction.** That original research contrast still requires a frozen continuous-time model and interpolation/support checks. No new empirical time model or scale-agreement ruling was computed. The total observation-time interpretation retains associated solar geometry; a secondary geometry/season-standardized pattern remains separate and support-dependent.

## Cloud support and remaining weaknesses

The 17 geometry-supported endpoint candidates span seven year-months. Common clear sample-point counts are **0, 3, 214, 240, 275, 300, 300 out of 300**. The largest observed gap, 3 to 214, defines the upper group prioritized for this bounded acquisition batch. This distribution-based priority is recorded in the selection freeze; it is not a new universal cloud cutoff or a pass-count target. The 2021 and 2022 strata remain in a cloud-support review queue. Their poor afternoon coverage is reported explicitly, not hidden as missing data. All 129 cloud assets across 29 screened passes were retrieved successfully.

Native valid-cell intersections were also checked within each selected year-month. Retaining the common cells would preserve {joint.retained_fraction_on_common_cells.min():.1%}–{joint.retained_fraction_on_common_cells.max():.1%} of individual pass cells. Counts, contributing blocks and canopy variation are in [within_stratum_native_cell_support.csv](within_stratum_native_cell_support.csv). These are support diagnostics; the new Stage 1 fits still use each pass's full valid footprint. Common-cell refits and registration stress tests remain needed for the added passes.

Month/year balance removes differences in the mix of those strata. It does **not** match weather or exact day of month: selected observations are still on different days. Some strata have only one pass in each arm; this is not five independent replicated seasons for each month. The original stable 2019–2025 median canopy and frozen context layers were retained for estimator comparability, so older acquisitions introduce more context-vintage mismatch. Annual-context sensitivity remains outstanding. Only the August 2019 pair satisfies the stricter 15-degree geometry sensitivity in both arms; the expanded sample still relies on the documented 25-degree pilot exception.

A separate, explicitly labeled synthetic check shows zero artificial window contrast after balancing when the simulated outcome depends only on month and year. Adding a within-month trend leaves residual bias, as expected. Its assumed 0.03 K pass noise is illustrative; this is neither an empirical effect nor a sample-size/power calculation. The synthetic output is under `tests/fixtures/synthetic_demo/rebalance_20260921/`.

## What this resolves and what remains

The sample now has repeated morning/afternoon coverage within the same year and month, and recorded weights prevent unequal pass counts from changing the seasonal comparison. The seven added paired fits and native-cell checks are complete. Full-summer coverage, weather/day-of-month balance, annual-context sensitivity, added-pass registration/common-cell fits, calibrated temporal uncertainty and Reza's scale tolerance remain unresolved. No professor approval or full multi-city rollout is implied. VPD remains descriptive; no eight-class unmixing was introduced.

The rationale is consistent with the [New York ECOSTRESS study's explicit warning about observations from different days](https://www.nature.com/articles/s41598-021-89972-0) and [NASA's description of variable observation times from the ISS](https://ai.jpl.nasa.gov/public/projects/ecostress/). The weighting and acquisition priority here are our documented design choices, not a sample-size recommendation from those papers.

## Evidence and reproducibility

The acquisition freeze and complete metadata/cloud ledgers are in `docs/v2/v6_2/execution/rebalance_20260921/`. Code is in `src/v6_2_rebalance/`. The eight new network-free selection tests check window boundaries, exact balancing with unequal counts, prohibition of cross-year matching, duplicate-pass rejection, known season-only bias removal, outcome independence, numeric revision selection and refusal to invent a cloud-priority split in ambiguous or missing data. Existing paired-model/native-footprint checks are also rerun. Input rasters, selection inputs, code and deliverables are checksum-bound. See [verification.json](verification.json), [balanced12_passes.csv](balanced12_passes.csv) and [new7_passes_and_precision.csv](new7_passes_and_precision.csv).
'''
(PKG/'README.md').write_text(doc)
for n in ['archive_month_time_counts.csv','matched_strata_cloud_support.csv','thermal_batch_selection_freeze.json']:
    shutil.copy2(OUT/n,PKG/n)
print(json.dumps({k:v for k,v in summary.items() if k!='native_cell_checks'},indent=2))
