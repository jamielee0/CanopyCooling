"""Descriptive weather only; no cooling regression or VPD effect claim."""
from pathlib import Path
import pandas as pd,numpy as np,json
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'deliverables/Methodology_and_Expansion_v6_2_20260921';d=pd.read_csv(OUT/'pass_gradients_exploratory.csv');cols=['city','orbit','acquisition_utc','vpd_kpa_inherited_metadata'];d=d[cols].copy()
p=ROOT/'data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/hrrr_hourly_domain_summary.csv';w=pd.read_csv(p);w['timestamp']=pd.to_datetime(w.timestamp_utc,utc=True);rows=[]
for r in d.itertuples(index=False):
 t=pd.Timestamp(r.acquisition_utc);h0=t.floor('h');h1=t.ceil('h');ww=w[w.city==r.city].drop_duplicates('timestamp').set_index('timestamp');rec=r._asdict();rec['weather_status']='MISSING_BRACKETING_HOURLY_RECORDS';rec['hrrr_t2m_K']=np.nan;rec['hrrr_vpd_kPa']=np.nan
 if h0 in ww.index and h1 in ww.index:
  a=0 if h0==h1 else (t-h0).total_seconds()/3600
  rec['hrrr_t2m_K']=float((1-a)*ww.loc[h0,'t2m_k']+a*ww.loc[h1,'t2m_k']);rec['hrrr_vpd_kPa']=float((1-a)*ww.loc[h0,'vpd_kpa']+a*ww.loc[h1,'vpd_kpa']);rec['weather_status']='LINEAR_INTERPOLATION_OF_EXISTING_HOURLY_DOMAIN_MEANS';rec['source']=str(p.relative_to(ROOT))
 rows.append(rec)
x=pd.DataFrame(rows);x.to_csv(OUT/'descriptive_vpd_temperature.csv',index=False);summ=[]
for city,q in x.groupby('city'):
 complete=q.dropna(subset=['hrrr_t2m_K','hrrr_vpd_kPa']);summ.append({'city':city,'selected_passes':len(q),'complete_existing_HRRR_pairs':len(complete),'sample_r_VPD_air_temperature':float(complete.hrrr_vpd_kPa.corr(complete.hrrr_t2m_K)) if len(complete)>=3 else None,'vpd_range_kPa':[float(complete.hrrr_vpd_kPa.min()),float(complete.hrrr_vpd_kPa.max())] if len(complete) else None,'interpretation':'descriptive subset; small incomplete sample, not causal VPD evidence or a common-support diagnostic'})
(OUT/'descriptive_vpd_summary.json').write_text(json.dumps({'inherited_design_evidence':'Advisor reports approximately 0.95 VPD-temperature correlation in arid cities and approximately 0.3 kPa LA common support; these are historical design diagnostics, not recomputed or relabeled as this pilot result.','source':str(p.relative_to(ROOT)),'source_product':'existing HRRR hourly domain means; interpolation as documented, not independent meteorological observations','current_sample':summ},indent=2));print(json.dumps(summ))
