import unittest
import numpy as np
import pandas as pd
from v6_2_advance.advisor_step2_models import assemble_inputs, fit_pass_model, arm_ratios


class Step2Tests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame({'city':['test']*6,'population':['original']*6,
            'orbit':range(6),'local_date':[f'd{i}' for i in range(6)],
            'shortwave_W_m2':[1.,2.,3.,1.,2.,3.], 'after_noon':[0,0,0,1,1,1],
            'cooling':[6.,6.,12.,8.,14.,14.]})

    def test_known_ols_coefficients_se_and_residual_sd(self):
        m=fit_pass_model(self.rows,'shortwave_W_m2')
        np.testing.assert_allclose(m.params,[2,3,4],atol=1e-12)
        np.testing.assert_allclose(m.bse,np.sqrt([16/3,1,8/3]),atol=1e-12)
        self.assertAlmostEqual(m.mse_resid,4)
        self.assertEqual(m.df_resid,3)
        np.testing.assert_allclose(m.resid,[1,-2,1,-1,2,-1],atol=1e-12)

    def test_predictor_rescaling_preserves_fit_and_after_noon(self):
        a=fit_pass_model(self.rows,'shortwave_W_m2'); r=self.rows.copy()
        r['sin_solar_elevation']=r.shortwave_W_m2/10
        b=fit_pass_model(r,'sin_solar_elevation')
        np.testing.assert_allclose(a.fittedvalues,b.fittedvalues,atol=1e-12)
        self.assertAlmostEqual(b.params['sin_solar_elevation'],30)
        self.assertAlmostEqual(b.params['after_noon'],4)

    def test_ratio_is_mean_of_ratios_not_ratio_of_means(self):
        a=arm_ratios(self.rows)[0]
        self.assertAlmostEqual(a['mean_cooling_over_shortwave'],13/3)
        self.assertNotEqual(a['mean_cooling_over_shortwave'],self.rows.iloc[:3].cooling.mean()/2)

    def test_missing_rank_duplicate_and_pooling_fail(self):
        for column,value in [('cooling',np.nan),('orbit',1),('local_date','d1'),('city','other'),('population','common')]:
            r=self.rows.copy();r.loc[0,column]=value
            with self.assertRaises(ValueError):fit_pass_model(r,'shortwave_W_m2')
        r=self.rows.copy();r.shortwave_W_m2=1
        with self.assertRaises(ValueError):fit_pass_model(r,'shortwave_W_m2')

    def test_nonpositive_radiation_ratio_rejected(self):
        r=self.rows.copy();r.loc[0,'shortwave_W_m2']=0
        with self.assertRaises(ValueError):arm_ratios(r)

    def test_unrequested_predictor_rejected(self):
        with self.assertRaises(ValueError):fit_pass_model(self.rows,'VPD_kPa')

    def fixture_tables(self):
        records=[];common=[]
        for i in range(23):
            city='atlanta' if 11<=i<16 else 'phoenix'
            date=f'2023-06-{i+1:02d}' if i<16 else f'2024-06-{i-15:02d}'
            y=1+i/100 if i<16 else np.nan
            records.append(dict(city=city,orbit=i,local_date=date,acquisition_utc=date+'T18:00:00Z',
                sample_role='main_2023' if i<16 else 'other_year_prediction_inputs_only',
                apparent_solar_hour=10 if i%2 else 15,after_noon=int(i%2==0),shortwave_W_m2=600+i,
                sin_solar_elevation=.5,solar_elevation_deg=30,cooling_K_per_10pp=y,
                cooling_q025_8km=y-.1,cooling_q975_8km=y+.1))
            if i<11:common.append(dict(city=city,orbit=i,date=date,group_km=8,quantity='temperature',
                units='K_per_10pp',original_point=y,common_point=y-.2,common_q025=y-.3,common_q975=y-.1))
        return pd.DataFrame(records),pd.DataFrame(common)

    def test_common_join_by_identity_and_only_2023_outcomes(self):
        table,common=self.fixture_tables()
        result=assemble_inputs(table.sample(frac=1,random_state=2),common.iloc[::-1])
        self.assertEqual(len(result),27)
        self.assertEqual(result.orbit.nunique(),16)
        for _,r in result.loc[result.population=='common'].iterrows():
            self.assertAlmostEqual(r.cooling,.8+r.orbit/100)
            self.assertEqual(r.shortwave_W_m2,600+r.orbit)

    def test_other_year_values_and_common_identity_mismatch_fail(self):
        table,common=self.fixture_tables();table.loc[16,'cooling_K_per_10pp']=0
        with self.assertRaises(ValueError):assemble_inputs(table,common)
        table,common=self.fixture_tables();common.loc[0,'date']='2023-07-01'
        with self.assertRaises(ValueError):assemble_inputs(table,common)
        table,common=self.fixture_tables();common.loc[0,'original_point']=-1
        with self.assertRaises(ValueError):assemble_inputs(table,common)


if __name__=='__main__':unittest.main()
