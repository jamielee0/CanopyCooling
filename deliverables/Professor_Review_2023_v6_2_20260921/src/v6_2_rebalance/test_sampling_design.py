import unittest
import numpy as np
import pandas as pd
from sampling_design import balanced_weights,classify_time,revision_dedup,cloud_priority_split

class SamplingTests(unittest.TestCase):
    def test_cloud_priority_natural_gap_is_order_invariant(self):
        a=[300,0,240,3,214,300,275]
        self.assertEqual(cloud_priority_split(a),(3,214))
        self.assertEqual(cloud_priority_split(a[::-1]),(3,214))
    def test_no_cloud_separation_cannot_create_a_cutoff(self):
        for a in [[300,300],[0,10,20],[0,float('nan'),300]]:
            with self.assertRaises(ValueError):cloud_priority_split(a)

    def test_endpoint_boundaries(self):
        self.assertEqual(list(classify_time([9.49,9.5,11.49,11.5,14.99,15,17.99,18])),['outside','morning','morning','middle','middle','afternoon','afternoon','outside'])
    def test_equal_season_weights_unequal_pass_counts(self):
        d=pd.DataFrame({'orbit':range(8),'year_month':['2023-06']*2+['2023-08']*3+['2023-09']*2+['2024-06'],'time_window':['morning','afternoon','morning','morning','afternoon','afternoon','middle','morning']})
        w=balanced_weights(d)
        np.testing.assert_allclose(w.balanced_arm_weight,[.5,.5,.25,.25,.5,0,0,0])
        for arm in ['morning','afternoon']:self.assertAlmostEqual(w[w.time_window.eq(arm)].balanced_arm_weight.sum(),1)
    def test_no_cross_year_matching_and_duplicates_rejected(self):
        d=pd.DataFrame({'orbit':[1,2],'year_month':['2023-06','2024-06'],'time_window':['morning','afternoon']})
        self.assertEqual(balanced_weights(d).balanced_arm_weight.sum(),0)
        with self.assertRaises(ValueError):balanced_weights(pd.concat([d,d]))
    def test_known_season_only_confounding_removed(self):
        d=pd.DataFrame({'orbit':range(5),'year_month':['2023-06']*2+['2023-08']*3,'time_window':['morning','afternoon','morning','morning','afternoon'],'fake_y':[1,1,3,3,3]})
        w=balanced_weights(d);means={a:np.sum(g.fake_y*g.balanced_arm_weight) for a,g in w.groupby('time_window')}
        self.assertAlmostEqual(means['afternoon']-means['morning'],0)
        self.assertNotAlmostEqual(d[d.time_window.eq('afternoon')].fake_y.mean()-d[d.time_window.eq('morning')].fake_y.mean(),0)
    def test_selection_independent_of_outcome(self):
        d=pd.DataFrame({'orbit':[1,2],'year_month':['2023-06']*2,'time_window':['morning','afternoon'],'arbitrary_gradient':[100,-100]})
        a=balanced_weights(d);d.arbitrary_gradient*=10000;b=balanced_weights(d)
        np.testing.assert_array_equal(a.balanced_arm_weight,b.balanced_arm_weight)
    def test_revision_is_numeric(self):
        rows=[dict(orbit=1,scene=1,tile='12SVC',granule_id='ECOv002_L2T_LSTE_00001_001_12SVC_20230601T170000_'+b+'_'+r) for b,r in [('999','09'),('1000','01'),('1000','10')]]
        self.assertTrue(revision_dedup(rows).granule_id.iloc[0].endswith('1000_10'))

if __name__=='__main__':unittest.main()
