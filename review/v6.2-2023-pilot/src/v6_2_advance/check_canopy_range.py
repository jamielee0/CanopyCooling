"""SYNTHETIC_DATA: same curved response, different observed canopy distributions."""
from pathlib import Path
import sys,json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.pooled_city_pass import fit_city_pass,CONTEXT
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
refs=json.loads((ROOT/'outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json').read_text());f0=refs['f0'];f1=refs['f1'];a=-5.;b=2.;expected=a*(f1-f0)+b*(f1**2-f0**2);rows=[]
for city,orbit in [('phoenix',27963),('atlanta',27835)]:
 p=ROOT/f'outputs/v6_2/sealed_coefficients/pooled_pilot_20260919_{city}/{orbit}_paired_native_cells_SEALED.parquet'
 d=pd.read_parquet(p,columns=['block','canopy_fraction',*CONTEXT]);f=d.canopy_fraction.to_numpy();_,ids=np.unique(d.block,return_inverse=True);d['LST_K']=305+.1*np.sin(ids)+a*f+b*f*f;d['canopy_squared']=f*f
 linear=fit_city_pass(d,outcomes=('LST_K',),bootstrap_replicates=2)
 quadratic=fit_city_pass(d,outcomes=('LST_K',),context=(*CONTEXT,'canopy_squared'),bootstrap_replicates=2)
 j=quadratic.predictor_names.index('canopy_squared');delta=.1*quadratic.coefficients[0,0]+(f1*f1-f0*f0)*quadratic.coefficients[j,0]
 assert np.isclose(delta,expected,atol=1e-8),'Known quadratic contrast was not recovered'
 rows.append({'label':'SYNTHETIC_DATA','city_support_only':city,'source_orbit_support_only':orbit,'observed_thermal_outcomes_used':False,'cells':len(d),'common_curve':'T=305+0.1*sin(block_index)-5*f+2*f^2','linear_gradient_K_per_10pp':float(.1*linear.coefficients[0,0]),'quadratic_standardized_gradient_K_per_10pp':float(delta),'known_standardized_gradient_K_per_10pp':float(expected),'reference_f0':f0,'reference_f1':f1,'canopy_median':float(np.median(f))})
p=guarded_output_path(ROOT,'synthetic','advance_20260921/canopy_range_SYNTHETIC_DATA.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'label':'SYNTHETIC_DATA','interpretation':'A mechanism demonstration, not evidence that the actual city response follows this chosen curve. Same temperature-space response in both cities; no T-fourth-power transformation. Shows why harmonizing contrast endpoints alone does not harmonize globally fitted linear slopes.','rows':rows},indent=2));print(json.dumps(rows,indent=2))
