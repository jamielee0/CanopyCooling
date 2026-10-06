import unittest
import numpy as np
import pandas as pd
from v6_2_advance.canopy_support import (
 assert_predictor_columns,band_mask,endpoint_support,distribution,protected_design,
 group_statistics,resampled_design_rank,quadratic_contrast,weighted_scaling,cross_distances,
)


def fixture():
 rows=[]
 for i,offset in enumerate((0,.15,.4)):
  for f in (.02,.07,.13,.22,.3):rows.append(dict(block=f"{i*8}_0",canopy_fraction=f+offset))
 return pd.DataFrame(rows)


class CanopySupportTests(unittest.TestCase):
 def test_outcome_columns_refused(self):
  assert_predictor_columns(["cell_id","block","canopy_fraction"])
  for x in ("LST_K","M_W_m2","emissivity","unknown"):
   with self.assertRaises(ValueError):assert_predictor_columns([x])
 def test_raw_square_before_block_centering_recovers_known_curve(self):
  f=fixture();d=protected_design(f,context=());x=f.canopy_fraction.to_numpy()
  y=305-5*x+2*x*x+np.repeat([0,10,-10],5)
  yc=y-pd.Series(y).groupby(f.block).transform("mean").to_numpy()
  b=np.linalg.lstsq(d.scaled,yc,rcond=None)[0]/d.norms
  np.testing.assert_allclose(b,[-5,2],atol=1e-11)
  self.assertAlmostEqual(float(quadratic_contrast(b,.1,.2)),.44)
  centered=x-f.groupby("block").canopy_fraction.transform("mean").to_numpy()
  wrong_square=centered**2;wrong_square-=pd.Series(wrong_square).groupby(f.block).transform("mean").to_numpy()
  wrong=np.column_stack([centered,wrong_square]);residual=yc-wrong@np.linalg.lstsq(wrong,yc,rcond=None)[0]
  self.assertGreater(np.linalg.norm(residual),.05)
 def test_endpoint_prediction_changes_both_terms(self):
  correct=quadratic_contrast(np.array([[-5,-30],[2,9]]),.1,.2)
  np.testing.assert_allclose(correct,[.44,2.73])
  self.assertNotAlmostEqual(correct[0],.5)
 def test_protected_quadratic_term_not_dropped_to_rescue_confounding(self):
  f=fixture();f["control"]=f.canopy_fraction**2
  with self.assertRaisesRegex(ValueError,"not identifiable"):protected_design(f,context=("control",))
 def test_two_unique_canopy_values_do_not_identify_quadratic(self):
  f=pd.DataFrame(dict(block=["0_0"]*6+["8_0"]*6,canopy_fraction=[.1,.2]*6))
  with self.assertRaisesRegex(ValueError,"not identifiable"):protected_design(f,context=())
 def test_context_dependency_selection_precedes_protected_basis(self):
  f=fixture();f["a"]=np.tile([0,1,-1,2,-2],3);f["b"]=2*f.a
  d=protected_design(f,context=("a","b"))
  self.assertEqual(d.diagnostics["protected_terms"],2)
  self.assertEqual(len(d.diagnostics["removed_context_terms"]),1)
  self.assertEqual(d.diagnostics["rank"],3)
 def test_neighbourhood_counts_are_not_endpoint_support(self):
  f=pd.DataFrame(dict(block=["0_0"]*4,canopy_fraction=[.05,.10,.17,.19]))
  r,_,_=endpoint_support(f,.1,.2,.025)
  self.assertEqual(r["upper_cells"],1)
  self.assertEqual(r["spanning_blocks"],0)
  self.assertEqual(r["endpoint_status"],"NO_BLOCK_SPANS_BOTH_ENDPOINTS")
 def test_clipped_band_density_and_overlap_are_explicit(self):
  mask,lo,hi=band_mask([0,.01,.03],0,.025)
  self.assertEqual((lo,hi),(0,.025));self.assertEqual(mask.sum(),2)
  f=pd.DataFrame(dict(block=["0_0"]*3,canopy_fraction=[.2,.25,.3]))
  r,_,_=endpoint_support(f,.2,.3,.05)
  self.assertEqual(r["cells_in_both_neighbourhoods"],1)
  self.assertEqual(r["reference_cells"],3)
  self.assertEqual(r["reference_whole_native_area_km2"],.0147)
 def test_no_arbitrary_canopy_floor(self):
  f=pd.DataFrame(dict(block=["0_0"]*4,canopy_fraction=[0,.00001,.00002,.2]))
  r,_,_=endpoint_support(f,0,.1,.01)
  self.assertEqual(r["reference_cells"],4);self.assertEqual(r["lower_cells"],3)
  self.assertEqual(distribution([])["n"],0);self.assertIsNone(distribution([])["median"])
 def test_same_spatial_draws_and_determinism(self):
  f=fixture();linear=protected_design(f,quadratic=False,context=());quad=protected_design(f,context=())
  a=resampled_design_rank(linear,quad,size=8,replicates=20,seed=77)
  b=resampled_design_rank(linear,quad,size=8,replicates=20,seed=77)
  self.assertEqual(a,b);self.assertEqual(a["groups"],3)
  self.assertEqual(a["paired_estimable"]+a["paired_failed"],20)
 def test_whole_block_grouping_uses_physical_coordinates(self):
  f=fixture();d=protected_design(f,context=());groups,_,xx=group_statistics(d,8)
  np.testing.assert_array_equal(groups,["0_0","1_0","2_0"])
  np.testing.assert_allclose(xx.sum(axis=0),d.scaled.T@d.scaled)
 def test_equal_city_equal_pass_scaling_and_known_distance(self):
  samples=[dict(city="a",values=np.array([[0.],[0.]])),dict(city="a",values=np.array([[2.]])),dict(city="b",values=np.array([[4.]]))]
  mean,sd=weighted_scaling(samples)
  self.assertAlmostEqual(mean[0],2.5);self.assertAlmostEqual(sd[0],np.sqrt(2.75))
  r=cross_distances(np.array([[0.,0.],[3.,4.]]),np.array([[0.,0.]]),np.zeros(2),np.ones(2))
  self.assertEqual(r["max"],5);self.assertEqual(r["median"],2.5)


if __name__=="__main__":unittest.main()
