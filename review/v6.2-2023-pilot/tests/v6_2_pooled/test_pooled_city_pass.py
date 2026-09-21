import unittest, json,sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(next(p/'src' for p in Path(__file__).resolve().parents if (p/'src/urban_cooling_v2').is_dir())))
from urban_cooling_v2.pooled_city_pass import *

class PooledTests(unittest.TestCase):
 def frame(self):
  rng=np.random.default_rng(3);n=1000;b=np.repeat(np.arange(20),50)
  f=.005*rng.normal(size=n)+.015*b+.1 # every block much narrower than .20
  x=rng.normal(size=n);y=290+2*b-8*f+3*x
  return pd.DataFrame(dict(block=b.astype(str),canopy_fraction=f,context=x,LST_K=y,M_W_m2=emitted_energy(y,.97)))
 def test_known_slope_with_large_between_block_confounding(self):
  d=self.frame();f=fit_city_pass(d,outcomes=('LST_K',),context=('context',),bootstrap_replicates=40)
  self.assertAlmostEqual(f.coefficients[0,0]*.1,-.8,places=9)
  self.assertEqual(f.diagnostics['contributing_blocks'],20)
  self.assertLess(f.diagnostics['LST_K_SE_per_10pp'],1e-9)
 def test_duplicate_block_bootstrap_equivalence(self):
  d=self.frame();d['LST_K']+=np.random.default_rng(2).normal(0,.3,len(d))
  f=fit_city_pass(d,outcomes=('LST_K',),context=('context',),bootstrap_replicates=10,seed=1)
  labels=np.unique(d.block);counts=np.random.default_rng(1).multinomial(len(labels),np.ones(len(labels))/len(labels));parts=[]
  for label,count in zip(labels,counts):
   for j in range(count):
    q=d[d.block==label].copy();q['block']=label+'_'+str(j);parts.append(q)
  brute=fit_city_pass(pd.concat(parts),outcomes=('LST_K',),context=('context',),bootstrap_replicates=2)
  np.testing.assert_allclose(f.bootstrap_coefficients[0],brute.coefficients,rtol=1e-8)
 def test_rank_does_not_rescue_canopy_by_dropping_confounder(self):
  d=self.frame();d['context']=d.canopy_fraction
  with self.assertRaisesRegex(ValueError,'not identifiable'): fit_city_pass(d,context=('context',),bootstrap_replicates=10)
 def test_context_dependencies_logged(self):
  d=self.frame();d['constant']=1;d['copy']=2*d.context
  f=fit_city_pass(d,context=('context','copy','constant'),bootstrap_replicates=5)
  self.assertEqual(len(f.diagnostics['removed_context_terms']),2)
 def test_paired_bootstrap_and_public_boundary(self):
  d=self.frame();d['M_W_m2']=5*d.LST_K
  f=fit_city_pass(d,context=('context',),bootstrap_replicates=10)
  np.testing.assert_allclose(f.bootstrap_coefficients[:,:,1],5*f.bootstrap_coefficients[:,:,0],rtol=1e-8)
  p=public_precision(f,city='TEST',pass_id='SYNTHETIC_DATA')
  self.assertFalse(any(t in p for t in ['coefficients','bootstrap_coefficients','mu0','mu1']))
  self.assertFalse(any('q025' in k or 'q975' in k for k in p))
 def test_nonfinite_not_silently_dropped_in_one_space(self):
  d=self.frame();d.loc[0,'M_W_m2']=np.nan
  with self.assertRaises(ValueError): fit_city_pass(d,context=('context',),bootstrap_replicates=2)
 def test_units_and_exact_inversion(self):
  m0=emitted_energy(310,.96);m1=emitted_energy(309,.96)
  self.assertAlmostEqual(float(temperature_equivalent(m1-m0,310,.96)),-1,places=10)
  with self.assertRaises(ValueError): temperature_equivalent(-m0,310,.96)
  with self.assertRaises(ValueError): emitted_energy(310,96)
 def test_simulation_zero_and_endpoints(self):
  f=np.array([0,.5,1]);t,m,e=mix_pixels(f,320,.97,0)
  np.testing.assert_allclose(t,320)
  t,m,e=mix_pixels(f,320,.97,10)
  self.assertAlmostEqual(t[0],320);self.assertAlmostEqual(t[-1],310)
  self.assertGreater(t[1],315)
 def test_reference_prediction_preserves_training_centers(self):
  d=self.frame();d.canopy_fraction=np.tile(np.linspace(.1,.6,50),20);d.LST_K=300-8*d.canopy_fraction+3*d.context
  f=fit_city_pass(d,outcomes=('LST_K',),context=('context',),bootstrap_replicates=5)
  p=f.prediction_difference(d,.2,.3);self.assertAlmostEqual(p['delta'][0],-.8,places=9)
  with self.assertRaises(ValueError): f.prediction_difference(d,.7,.8)
 def test_no_unapproved_ruling(self):
  self.assertEqual(scale_ruling(.1,.2,None),'PENDING_COEFFICIENT_RELEASE')
  self.assertEqual(scale_ruling(.1,.2,None,released=True),'PENDING_REZA_TOLERANCE')
  self.assertEqual(scale_ruling(.1,-.01,.2,released=True),'EMITTED_ENERGY_PRIMARY_LST_SCALE_DEPENDENT')
  self.assertEqual(scale_ruling(0,.01,.2,released=True),'DIRECTION_UNRESOLVED_AT_ZERO')
if __name__=='__main__': unittest.main()
