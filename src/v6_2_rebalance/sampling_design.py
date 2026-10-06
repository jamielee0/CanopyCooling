"""Outcome-free Phoenix sampling audit; no LST or model-result reads.

The audit freezes a feasible sampling design, not an empirical time contrast.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, sys
import numpy as np
import pandas as pd

ORIGINAL = [27963,28024,28085,28192,28706,28828,28909,28970,29092,29545,29606]

def classify_time(hours):
    h = np.asarray(hours, dtype=float)
    return np.select([(h>=9.5)&(h<11.5),(h>=11.5)&(h<15),(h>=15)&(h<18)],
                     ['morning','middle','afternoon'], default='outside')

def revision_dedup(rows):
    d = pd.DataFrame(rows).copy()
    d['build'] = d.granule_id.str.split('_').str[-2].astype(int)
    d['revision'] = d.granule_id.str.split('_').str[-1].astype(int)
    return d.sort_values(['build','revision','granule_id']).drop_duplicates(['orbit','scene','tile'],keep='last')

def balanced_weights(frame):
    """Equal year-month and equal morning/afternoon mass; keep every pass.

    Weights sum to one separately within each arm. Unsupported strata get zero.
    The difference of weighted arm means is a window contrast, not a 10.5/16
    interpolation. No outcome, standard error, cloud cutoff, or fitted sign used.
    """
    d=frame.copy()
    if d.orbit.duplicated().any(): raise ValueError('Duplicate physical passes')
    ends=d[d.time_window.isin(['morning','afternoon'])]
    both=ends.groupby('year_month').time_window.nunique()
    supported=both[both.eq(2)].index
    d['balanced_arm_weight']=0.0
    chosen=d.year_month.isin(supported)&d.time_window.isin(['morning','afternoon'])
    if len(supported):
        n=d.loc[chosen].groupby(['year_month','time_window']).orbit.transform('size')
        d.loc[chosen,'balanced_arm_weight']=1/(len(supported)*n)
    d['balanced_season_supported']=d.year_month.isin(supported)
    return d

def cloud_priority_split(counts):
    """Find a unique observed gap for acquisition priority, not a QA gate."""
    values=np.asarray(counts,dtype=float)
    if not np.isfinite(values).all() or (values<0).any():
        raise ValueError('Missing or invalid cloud support must be resolved')
    v=np.unique(values)
    if len(v)<2: raise ValueError('No observed support separation')
    gaps=np.diff(v)
    if (gaps==gaps.max()).sum()!=1:raise ValueError('Ambiguous support separation')
    k=int(gaps.argmax())
    return float(v[k]),float(v[k+1])


def main(root):
    sys.path.insert(0,str(root/'src'))
    from urban_cooling_v2.independent_foundation_audit import local_solar_hour
    out=root/'docs/v2/v6_2/execution/rebalance_20260921';out.mkdir(parents=True,exist_ok=True)
    sources={
      'catalogue':root/'docs/v2/v6_2/execution/catalogue_phoenix_002.json',
      'geometry':root/'data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/geometry_pass_summary.csv',
      'cloud':root/'data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/cloud_pass_summary.csv',
      'domain_index':root/'docs/v2/v6_2/execution/advance_20260921/candidate_domain_index.json'}
    cat=json.loads(sources['catalogue'].read_text());c=revision_dedup(cat['granules'])
    c['dt']=pd.to_datetime(c.acquisition_utc,utc=True,format='mixed')
    # Earliest scene time defines an orbit's representative acquisition. Scenes
    # may differ by about a minute; historical fit metadata remain unchanged.
    d=c.groupby('orbit').agg(acquisition_utc=('dt','min'),tiles=('tile','nunique'),granules=('granule_id','size')).reset_index()
    local=d.acquisition_utc.dt.tz_convert('America/Phoenix')
    d['local_date']=local.dt.strftime('%Y-%m-%d');d['clock_MST']=local.dt.strftime('%H:%M:%S')
    d['year']=local.dt.year;d['month']=local.dt.month;d['year_month']=local.dt.strftime('%Y-%m')
    d=d[d.year.between(2019,2025)&d.month.between(6,9)].copy()
    idx={x['city']:x for x in json.loads(sources['domain_index'].read_text())}
    lon=idx['phoenix']['longitude']
    d['solar_hour']=d.acquisition_utc.map(lambda t:local_solar_hour(t.to_pydatetime(),lon))
    d['time_window']=classify_time(d.solar_hour)
    g=pd.read_csv(sources['geometry']);g=g[g.city.eq('phoenix')]
    cols=['orbit','l1b_view_zenith_abs_p95_deg','l1b_geometry_coverage_fraction','geometry_definitive','scene_source_evidence_sha256']
    d=d.merge(g[cols],on='orbit',how='left',validate='one_to_one')
    d['geometry_status']=np.where(d.geometry_definitive.astype(str).str.lower().eq('true'), 'verified','unresolved')
    d['pilot_geometry_eligible']=d.geometry_status.eq('verified')&d.l1b_view_zenith_abs_p95_deg.le(25)&d.l1b_geometry_coverage_fraction.ge(.95)
    d['strict15_geometry_eligible']=d.geometry_status.eq('verified')&d.l1b_view_zenith_abs_p95_deg.le(15)&d.l1b_geometry_coverage_fraction.ge(.95)
    d['previously_processed_2023']=d.orbit.isin(ORIGINAL)
    cloud=pd.read_csv(sources['cloud']);cloud=cloud[cloud.city.eq('phoenix')]
    d=d.merge(cloud[['orbit','clear_domain_fraction','cloud_asset_complete','cloud_asset_set_sha256']],on='orbit',how='left',validate='one_to_one')
    d=d.sort_values('acquisition_utc');d.to_csv(out/'archive_pass_audit.csv',index=False)
    counts=pd.MultiIndex.from_product([range(2019,2026),range(6,10),['morning','middle','afternoon','outside']],names=['year','month','time_window']).to_frame(index=False)
    for label,mask in [('catalogue',np.ones(len(d),bool)),('geometry25',d.pilot_geometry_eligible),('geometry15',d.strict15_geometry_eligible),('processed11',d.previously_processed_2023)]:
        n=d[mask].groupby(['year','month','time_window']).size().rename(label+'_passes').reset_index()
        counts=counts.merge(n,how='left',on=['year','month','time_window']).fillna({label+'_passes':0})
        counts[label+'_passes']=counts[label+'_passes'].astype(int)
    counts.to_csv(out/'archive_month_time_counts.csv',index=False)
    current=balanced_weights(d[d.previously_processed_2023])
    current['role']=np.select([current.balanced_arm_weight.gt(0),current.balanced_season_supported],
      ['balanced_window_comparison','within_supported_season_middle_time'],default='descriptive_only_unmatched_season')
    current.to_csv(out/'current11_rebalanced_roles.csv',index=False)
    expanded=balanced_weights(d[d.pilot_geometry_eligible])
    proposed=expanded[expanded.balanced_arm_weight.gt(0)].copy()
    proposed['status']='GEOMETRY_SUPPORTED_CANDIDATE_NOT_NEW_COMPLETED_FIT'
    proposed.to_csv(out/'matched_year_month_candidates.csv',index=False)
    # All 2023 endpoint opportunities, plus supported multiyear candidates, get
    # identical cloud-point screening. No temperature-dependent QC is read.
    screen=d[(d.year.eq(2023)&d.time_window.isin(['morning','afternoon']))|d.orbit.isin(proposed.orbit)]
    screen.to_csv(out/'cloud_screen_population.csv',index=False)
    design={
      'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'user_request':'rebalance passes, potentially adding/removing; bounded Phoenix sampling correction within v6.2',
      'catalogue_audit':cat['audit'],'scope':'2019-2025 local June-September Phoenix C2 catalogue; complete metadata, inherited geometry census, targeted nonthermal cloud screen',
      'no_new_thermal_values_read':True,'prior_disclosure':'The eleven existing Phoenix gradients were already disclosed. This is an exploratory design amendment, not a globally blinded design.',
      'time_windows_solar_hours':{'morning':[9.5,11.5],'middle':[11.5,15.0],'afternoon':[15.0,18.0]},
      'window_rationale':'Reuse previously published metadata-screen morning/afternoon windows. These define comparison support, not new cloud/canopy eligibility thresholds. No claim that window means equal exactly 10:30 and 16:00.',
      'date_rule':'Phoenix local civil year-month, MST UTC-7; earliest scene time of latest revisions in each physical orbit, centroid apparent solar time. Historical model timestamps unchanged.',
      'geometry_rule':'Reuse pilot exception p95 absolute view zenith <=25 degrees and >=0.95 geometry coverage with definitive geometry; also report <=15-degree sensitivity. Unresolved is not failed.',
      'weights':'For S supported year-month strata, each endpoint pass has arm weight 1/(S*n_stratum_arm). Weights sum to one in each arm. All available passes within supported strata retained; no inverse-SE weighting.',
      'current11_supported_endpoint_orbits':current.loc[current.balanced_arm_weight.gt(0),'orbit'].tolist(),
      'all11_preserved':True,'candidate_orbits':proposed.orbit.tolist(),
      'candidate_status':'geometry-screen candidates only; cloud/common-footprint/context support and Stage1 precision must be established before adding to completed sample',
      'no_cloud_or_canopy_cutoff_added':True,'no_pass_count_target_added':True,
      'no_new_empirical_time_model_fitted':True,
      'estimand':'Balanced window comparison is a sampling sensitivity. Exact 10:30-versus-16:00 contrast still needs continuous-time model and interpolation support; retain total solar-geometry-associated time pattern and separate secondary geometry/season standardization.',
      'limits':['Calendar-month equality does not balance day of month, weather, view geometry, or native-cell composition.','No July/September 2023 morning observation can be manufactured by weighting.','Broader geometry-unresolved orbits remain in the audit, not silently excluded as unsuitable.','Do not pool morning from one year with afternoon from another as if matched.'],
      'input_sha256':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in sources.items()},
      'source_paths':{k:str(p.relative_to(root)) for k,p in sources.items()},
      'data_link_target':str((root/'data').resolve())}
    freeze=out/'selection_design.json'
    if freeze.exists():
        old=json.loads(freeze.read_text());assert old['input_sha256']==design['input_sha256'];assert old['candidate_orbits']==design['candidate_orbits']
    else:freeze.write_text(json.dumps(design,indent=2)+'\n')
    print(json.dumps({'archive_summer_orbits':len(d),'current_supported_endpoints':len(current[current.balanced_arm_weight.gt(0)]),'multiyear_candidates':len(proposed),'candidate_strata':proposed.year_month.nunique(),'cloud_screen_passes':len(screen)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
