import unittest
import numpy as np
import pandas as pd
from urban_cooling_v2.pooled_city_pass import SIGMA
from v6_2_advance.spatial_review import block_stats
from v6_2_advance.time_resampling import day_cluster_benchmark
from v6_2_advance.window_uncertainty import (
 joint_passes,window_quantities,summarize,precision_only,day_slope_bank,stratified_window_bank,
 nuisance_design,moment_variance_intervals,covariance_root,simulate_scenario,
)

def frame(offset=0):
 rows=[]
 for b,slope in enumerate((-3.,-5.,-8.)):
  for f in (.01,.08,.2,.4):rows.append(dict(block=f'{b*8}_0',canopy_fraction=f,LST_K=300+b+slope*f+offset*f,M_W_m2=450+2*b+6*(slope+offset)*f))
 return pd.DataFrame(rows)

class WindowTests(unittest.TestCase):
 def test_joint_order_and_absent_blocks_preserve_physical_identity(self):
  a=frame();b=frame(1);b=b[b.block.ne('16_0')]
  stats=[block_stats(x,['canopy_fraction']) for x in (a,b)]
  point,draws,audit=joint_passes(stats,group_km=8,replicates=30,seed=18)
  p2,d2,a2=joint_passes([block_stats(x.sample(frac=1,random_state=1),['canopy_fraction']) for x in (a,b)],group_km=8,replicates=30,seed=18)
  np.testing.assert_allclose(draws,d2,equal_nan=True);self.assertEqual(audit,a2)
  self.assertEqual(audit['structural_absent_groups'],[0,1]);self.assertEqual(audit['groups'],3)
 def test_joint_draw_equals_explicit_duplicated_block_fit(self):
  f=frame();s=block_stats(f,['canopy_fraction']);_,draws,_=joint_passes([s],group_km=8,replicates=10,seed=7)
  rng=np.random.default_rng(7)
  for r in range(10):
   counts=rng.multinomial(3,np.full(3,1/3));parts=[]
   # Counts are ordered by coarse physical group, not lexicographic fine labels.
   for label,count in zip(['0_0','8_0','16_0'],counts):
    for j in range(count):
     q=f[f.block.eq(label)].copy();q.block=f'{label}:copy{j}';parts.append(q)
   expected=-.1*block_stats(pd.concat(parts),['canopy_fraction']).solve()[0]
   np.testing.assert_allclose(draws[r,0],expected,atol=1e-11)
 def test_shared_geography_identical_passes_cancel(self):
  s=block_stats(frame(),['canopy_fraction']);point,draws,_=joint_passes([s,s],group_km=1,replicates=20,seed=3)
  np.testing.assert_array_equal(draws[:,0]-draws[:,1],0)
  result=window_quantities(draws,[1,-1],300,.95);np.testing.assert_array_equal(result,0)
 def test_nonestimable_pass_does_not_delete_unrelated_draw_values(self):
  a=frame();b=a[a.block.eq('0_0')];stats=[block_stats(x,['canopy_fraction']) for x in (a,b)]
  _,draws,audit=joint_passes(stats,group_km=1,replicates=100,seed=6)
  self.assertGreater(len(audit['per_pass_failed_indices'][1]),0)
  self.assertTrue(np.isfinite(draws[:,0]).all())
 def test_arm_aggregation_before_exact_inversion(self):
  ref=300.;e=.95;ce=np.array([1.,3.,0.,0.]);flux=e*SIGMA*(ref**4-(ref-ce)**4)
  values=np.column_stack([ce,flux]);r=window_quantities(values,[.5,.5,-.5,-.5],ref,e)
  self.assertAlmostEqual(r[0],2)
  expected=ref-(ref**4-(flux[0]+flux[1])/(2*e*SIGMA))**.25
  self.assertAlmostEqual(r[2],expected)
  self.assertGreater(abs(r[2]-2),.001)
 def test_inactive_nonestimable_dates_do_not_poison_window(self):
  c=np.array([[1.,5.],[.5,3.],[np.nan,np.nan]])
  r=window_quantities(c,[1,-1,0],300,.95);self.assertAlmostEqual(r[0],.5)
  with self.assertRaises(ValueError):window_quantities(c,[.5,-1,0],300,.95)
 def test_invalid_reference_anchor_reported(self):
  c=np.array([[1,1e6],[0,0]],float);r=window_quantities(c,[1,-1],300,.95)
  self.assertTrue(np.isnan(r[2]));self.assertEqual(r[0],1)
 def test_public_serialization_rejects_effects(self):
  row=dict(comparison='combined',group_km=8,quantity='temperature',units='K',independent_dates=5,requested=100,
   estimable=100,failed=0,SE=.1,width95=.4,effect_status='SEALED_USER_REQUEST',uncertainty_scope='fixed_dates_spatial_only')
  precision_only(row)
  for key in ('point','q025','significant','effect_sign'):
   with self.assertRaises(ValueError):precision_only({**row,key:0})
 def test_benchmark_bank_exactly_matches_existing_day_code(self):
  times=np.linspace(10,17,8);y=np.sin(times);days=np.array([f'2023-06-{d:02d}' for d in range(1,9)])
  point,bank,audit=day_slope_bank(times,early=10.5,late=16,replicates=100,seed=8)
  old=day_cluster_benchmark(times,y,days=days,early=10.5,late=16,replicates=100,seed=8)
  np.testing.assert_allclose(point@y,old['point'][0],atol=1e-12)
  np.testing.assert_allclose(bank@y,old['draws'][:,0],atol=1e-12)
  self.assertEqual(len(bank),old['estimable_resamples'])
 def test_stratified_bank_preserves_singletons_and_weights(self):
  w=np.array([.5,-.5,.5,-.25,-.25]);months=np.array([6,6,8,8,8])
  b=stratified_window_bank(w,months,replicates=30,seed=8)
  np.testing.assert_array_equal(b[:,:3],np.tile(w[:3],(30,1)));np.testing.assert_allclose(b.sum(axis=1),0)
  self.assertTrue(np.isin(b[:,3],[0,-.25,-.5]).all())
 def test_moment_variance_subtracts_spatial_noise_once(self):
  times=np.arange(8.)+10;months=np.array([6]*4+[8]*4);_,p,df=nuisance_design(times,months);s=np.eye(8)*.04
  vals,vec=np.linalg.eigh(p);direction=vec[:,np.argmax(vals)];y=direction*np.sqrt(np.trace(p@s))
  w=np.array([1,0,0,-1,0,0,0,0]);lo,hi,tau,df=moment_variance_intervals(y,w,s,times,months)
  self.assertAlmostEqual(tau[0],0,places=12)
  from scipy.stats import t
  self.assertAlmostEqual(float((hi-lo)[0]),2*t.ppf(.975,df)*np.sqrt(w@s@w),places=10)
 def test_covariance_known_answer_and_invalid_matrix(self):
  s=np.array([[4,1],[1,2.]])
  a=covariance_root(s);np.testing.assert_allclose(a@a.T,s)
  with self.assertRaises(ValueError):covariance_root(np.array([[1,2],[2,1.]]))
 def test_simulation_oracle_and_target_separation(self):
  d=dict(times=[10,11,12,14,15,16],months=[6,6,6,8,8,8],day_numbers=[1,3,8,60,63,70],weights=[-1,0,0,0,0,1])
  p,b,a=day_slope_bank(d['times'],early=10,late=16,replicates=99,seed=4)
  strat=np.tile(d['weights'],(99,1))
  r,truth=simulate_scenario(d,np.eye(6)*.001,amplitude=.3,day_sd=.15,correlation_fraction=1,profile='linear',datasets=5000,seed=891,banks=(p,b,a,strat))
  self.assertAlmostEqual(truth['population_target'],.3)
  self.assertGreater(r['oracle_known_variance']['population_target_coverage'],.93)
  self.assertLess(r['oracle_known_variance']['population_target_coverage'],.97)
  self.assertGreater(r['fixed_date_spatial_only']['fixed_dates_target_coverage'],.93)
  self.assertLess(r['fixed_date_spatial_only']['population_target_coverage'],.4)

if __name__=='__main__':unittest.main()
