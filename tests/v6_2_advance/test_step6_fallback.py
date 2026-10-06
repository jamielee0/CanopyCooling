import unittest
import numpy as np
import eccodes as ec
from pyproj import Proj

class Step6FallbackTests(unittest.TestCase):
 def test_spherical_stereographic_area_weights_against_projection_jacobian(self):
  p=Proj('+proj=stere +lat_0=90 +lat_ts=60 +lon_0=-105 +a=6371229 +b=6371229')
  lat=np.array([30.,33.,36.,40.]);analytic=(1+np.sin(np.deg2rad(lat)))**2
  independent=np.array([1/p.get_factors(-112,float(v)).areal_scale for v in lat])
  np.testing.assert_allclose(analytic/analytic[0],independent/independent[0],rtol=1e-8)
 def test_eccodes_element_lookup_with_list_has_correct_order_and_values(self):
  h=ec.codes_grib_new_from_samples('regular_ll_sfc_grib2')
  try:
   ec.codes_set(h,'Ni',2);ec.codes_set(h,'Nj',2);ec.codes_set_values(h,[1.,2.,3.,4.])
   np.testing.assert_array_equal(ec.codes_get_elements(h,'values',np.array([3,0,2]).tolist()),[4,1,3])
  finally:ec.codes_release(h)

if __name__=='__main__':unittest.main()
