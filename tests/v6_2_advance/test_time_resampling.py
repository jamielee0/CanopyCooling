import unittest,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from v6_2_advance.time_resampling import day_cluster_benchmark
from urban_cooling_v2.pilot_scale import time_contrast

class TimeResamplingTests(unittest.TestCase):
 def test_known_line_and_cluster_count(self):
  t=np.array([10.,10.,11.,12.,13.,14.,15.,16.,17.]);days=np.array(['a','a','b','c','d','e','f','g','h'])
  r=day_cluster_benchmark(t,2-.03*t,days=days,replicates=100)
  np.testing.assert_allclose(r['point'],[-.165],atol=1e-12)
  np.testing.assert_allclose(r['draws'],-.165,atol=1e-12)
  self.assertEqual(r['independent_days'],8)
 def test_uses_observed_response_once(self):
  rng=np.random.default_rng(421);t=np.linspace(10,18,24);y=rng.normal(size=(24,2));days=np.arange(24)
  a=day_cluster_benchmark(t,y,days=days,replicates=100,seed=12)
  b=time_contrast(t,y,day_clusters=days,bootstrap_CE=None,replicates=100,seed=12)
  np.testing.assert_array_equal(a['draws'],b['draws'])
 def test_refuses_unsupported_target(self):
  with self.assertRaisesRegex(ValueError,'outside observed support'):
   day_cluster_benchmark(np.arange(12,17),np.arange(5),days=np.arange(5))
if __name__=='__main__':unittest.main()
