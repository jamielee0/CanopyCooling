import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import t
from v6_2_advance.advisor_step3_prediction import verify_committed_bundle,temperature_estimate,coverage


class Step3Tests(unittest.TestCase):
    def test_individual_prediction_interval_has_residual_variance(self):
        d=pd.DataFrame({'x':[1,2,3,1,2,3],'a':[0,0,0,1,1,1],'y':[6,6,12,8,14,14]})
        m=smf.ols('y ~ x + a',d).fit();p=m.get_prediction(pd.DataFrame({'x':[2],'a':[0]})).summary_frame().iloc[0]
        self.assertAlmostEqual(p['mean'],8)
        self.assertAlmostEqual(p['mean_se'],np.sqrt(4/3))
        self.assertAlmostEqual(p.obs_ci_upper,8+t.ppf(.975,3)*np.sqrt(4+4/3))
        self.assertGreater(p.obs_ci_upper,p.mean_ci_upper)

    def test_sign_and_quantiles_select_temperature_canopy(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.npz';b=np.zeros((4,2,2));b[:,1,1]=[-1,-2,-3,-4]
            np.savez(p,predictor_names=['other','canopy_fraction'],outcome_names=['other','LST_K'],
                     coefficients=[[999,999],[999,-2.5]],bootstrap_coefficients=b)
            x=temperature_estimate(p)
            self.assertAlmostEqual(x['cooling'],.25);self.assertAlmostEqual(x['q025'],.1075)
            self.assertAlmostEqual(x['q975'],.3925);self.assertEqual(x['draws'],4)

    def test_pi_coverage_includes_boundaries_and_no_missing_fill(self):
        self.assertTrue(coverage(1,2,1,3)['inside_prediction_interval'])
        self.assertTrue(coverage(3,2,1,3)['inside_prediction_interval'])
        self.assertFalse(coverage(.99,2,1,3)['inside_prediction_interval'])
        with self.assertRaises(ValueError):coverage(np.nan,2,1,3)

    def test_gate_requires_matching_real_commit_and_unchanged_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp);p=r/'note.md';p.write_text('predictions before access\n');h=hashlib.sha256(p.read_bytes()).hexdigest()
            def git(*a):return subprocess.run(['git','-C',str(r),*a],check=True,capture_output=True,text=True).stdout.strip()
            git('init');git('add','note.md');git('-c','user.name=Unit Test','-c','user.email=test@example.invalid','commit','-m','Synthetic gate test')
            commit=git('rev-parse','HEAD')
            self.assertTrue(verify_committed_bundle(r,commit,{'note.md':h},r))
            with self.assertRaises(ValueError):verify_committed_bundle(r,'0'*40,{'note.md':h},r)
            p.write_text('changed prediction\n')
            with self.assertRaises(ValueError):verify_committed_bundle(r,commit,{'note.md':h},r)


if __name__=='__main__':unittest.main()
