"""SYNTHETIC_DATA calibration of the inherited two-stage resampling rule."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.pilot_scale import time_contrast
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
rng=np.random.default_rng(20260921);n=30;t=np.linspace(10,18,n);true_y=.7+.04*(t-10.5);true_delta=.04*5.5;measurement_sd=.10
rows=[]
for latent_sd in [0,.1,.3]:
 point=[];se_old=[];se_pairs=[]
 for k in range(300):
  y=true_y+rng.normal(0,np.sqrt(measurement_sd**2+latent_sd**2),n)
  b=y[:,None,None]+rng.normal(0,measurement_sd,(n,250,1))
  one=time_contrast(t,y,bootstrap_CE=b,replicates=500,seed=20260921+k)
  two=time_contrast(t,y,bootstrap_CE=None,replicates=500,seed=20260921+k)
  point.append(float(one['point'][0]));se_old.append(float(one['draws'][:,0].std(ddof=1)));se_pairs.append(float(two['draws'][:,0].std(ddof=1)))
 sd=float(np.std(point,ddof=1));old=float(np.sqrt(np.mean(np.square(se_old))));pairs=float(np.sqrt(np.mean(np.square(se_pairs))))
 rows.append({'label':'SYNTHETIC_DATA','passes':n,'simulated_datasets':300,'resamples_each':500,'measurement_sd_K_per_10pp':measurement_sd,'additional_between_pass_sd':latent_sd,'true_time_contrast':true_delta,'empirical_sampling_sd':sd,'inherited_combined_resampling_RMS_SE':old,'pairs_only_RMS_SE':pairs,'combined_to_pairs_variance_ratio':old**2/pairs**2,'inherited_normal_interval_coverage':float(np.mean(np.abs(np.array(point)-true_delta)<=1.96*np.array(se_old))),'pairs_only_normal_interval_coverage':float(np.mean(np.abs(np.array(point)-true_delta)<=1.96*np.array(se_pairs)))})
path=guarded_output_path(ROOT,'synthetic','advance_20260921/time_uncertainty_SYNTHETIC_DATA.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps({'label':'SYNTHETIC_DATA','purpose':'check double counting when resampling already noisy pass estimates and adding another independent copy of their first-stage noise','interpretation':'calibration diagnostic, not validation of an empirical time contrast or universal replacement; independent homoscedastic passes in this simulation; normal intervals are diagnostic only','rows':rows},indent=2));print(json.dumps(rows,indent=2))
