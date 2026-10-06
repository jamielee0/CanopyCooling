import unittest
import numpy as np
import pandas as pd
from v6_2_advance.released_window_sensitivity import reference_quadratic_stats
from v6_2_advance.spatial_review import block_stats
from v6_2_advance.window_uncertainty import joint_passes,window_quantities

def fixture(quadratic=True):
 rows=[]
 for b in range(4):
  for f in [.02,.08,.16,.28,.4]:rows.append(dict(block=f'{b*8}_0',canopy_fraction=f,
   LST_K=305+b*3-5*f+(2*f*f if quadratic else 0),M_W_m2=440+b*6-30*f+(9*f*f if quadratic else 0)))
 return pd.DataFrame(rows)

class ReleasedWindowSensitivityTests(unittest.TestCase):
 def test_reference_basis_known_finite_contrast(self):
  s=reference_quadratic_stats(fixture(),.1,.2,[])
  np.testing.assert_allclose(-.1*s.solve()[0],[.44,2.73],atol=1e-10)
 def test_equivalent_to_raw_square_model_for_point_and_counts(self):
  f=fixture();f['raw_square']=f.canopy_fraction**2
  a=block_stats(f,['canopy_fraction','raw_square']);b=reference_quadratic_stats(f,.1,.2,[])
  for counts in ([1,1,1,1],[0,3,1,0],[1,0,0,3]):
   raw=a.solve(counts);new=b.solve(counts)
   np.testing.assert_allclose(-.1*new[0],-(.1*raw[0]+.03*raw[1]),atol=1e-10)
 def test_linear_nested_model_has_zero_joint_change(self):
  f=fixture(False);a=block_stats(f,['canopy_fraction']);b=reference_quadratic_stats(f,.1,.2,[])
  point,draws,_=joint_passes([a,b],group_km=8,replicates=30,seed=88)
  np.testing.assert_allclose(draws[:,0],draws[:,1],atol=1e-10)
 def test_joint_window_variant_identity_and_frozen_weights(self):
  f=fixture();a=block_stats(f,['canopy_fraction']);q=reference_quadratic_stats(f,.1,.2,[])
  point,draws,_=joint_passes([a,a,q,q],group_km=8,replicates=20,seed=91)
  for pair in ([0,1],[2,3]):
   result=window_quantities(draws[:,pair,:],[1,-1],300,.95)
   np.testing.assert_allclose(result,0,atol=1e-10)

if __name__=='__main__':unittest.main()
