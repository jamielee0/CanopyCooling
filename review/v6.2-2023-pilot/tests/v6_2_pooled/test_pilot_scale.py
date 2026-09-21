import unittest,sys
from pathlib import Path
sys.path.insert(0,str(next(p/'src' for p in Path(__file__).resolve().parents if (p/'src/urban_cooling_v2').is_dir())))
import numpy as np,pandas as pd
from urban_cooling_v2.pilot_scale import *
class ScaleTests(unittest.TestCase):
 def test_time_total_does_not_adjust_solar_geometry(self):
  t=np.array([10,11,13,15,17]);y=np.column_stack([.2*t,.3*t]);r=time_contrast(t,y,replicates=25)
  np.testing.assert_allclose(r['point'],[1.1,1.65]);self.assertEqual(r['model'],'total_observation_time')
 def test_time_support_extrapolation_refused(self):
  with self.assertRaisesRegex(ValueError,'outside observed support'): time_contrast([12,13,14,15,16],[1,2,3,4,5])
 def test_geometry_confounding_refused(self):
  t=np.array([10,11,13,15,17]);g=np.array([60,62,70,20,15]);d=np.repeat(180,5)
  self.assertFalse(secondary_overlap(t,g,d,13.25))
  with self.assertRaisesRegex(ValueError,'common support absent'): time_contrast(t,t,geometry=g,day_of_year=d,replicates=2)
 def test_pair_uses_observed_support_not_quantile_exclusion(self):
  f=pd.DataFrame({'block':np.repeat(['a','b'],101),'canopy_fraction':np.r_[np.zeros(100),.15,np.linspace(.02,.14,101)]})
  f0,f1,refs=supported_reference_pair([f,f]);self.assertAlmostEqual(f1-f0,.1);self.assertEqual(refs[0].block.nunique(),2)
 def test_reference_absence_explicit(self):
  f=pd.DataFrame({'block':['a']*3,'canopy_fraction':[0,.01,.02]})
  with self.assertRaises(ValueError):supported_reference_pair([f])
 def test_zero_simulation_does_not_release_original_association(self):
  rng=np.random.default_rng(8);n=200;b=np.repeat(np.arange(10),20);f=np.tile(np.linspace(.1,.7,20),10)
  d=pd.DataFrame({'block':b.astype(str),'canopy_fraction':f,'LST_K':320-25*f+b*.1,'emissivity':.97})
  for c in CONTEXT:d[c]=rng.normal(size=n)
  r=simulate_pass(d,contrasts=(0,5),reference_K=310,reference_emissivity=.97,replicates=3)
  zero=[v for v in r if v['scenario']=='transformation_only' and v['constant_component_contrast_K']==0][0]
  self.assertAlmostEqual(zero['CE_T_K_per_10pp'],0,places=10)
  self.assertTrue(all(v['label']=='SYNTHETIC_DATA' for v in r))
if __name__=='__main__':unittest.main()
