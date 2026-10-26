from pathlib import Path
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
p=Path(__file__).resolve().parent
train=pd.read_csv(p/'training_11.csv'); targets=pd.read_csv(p/'target_inputs_7.csv')
fit=smf.ols('cooling ~ shortwave_W_m2 + after_noon',data=train,missing='raise').fit()
actual=fit.get_prediction(targets).summary_frame(alpha=.05)
saved=pd.read_csv(p/'predictions_7.csv')
for key in actual:np.testing.assert_allclose(actual[key],saved[key],atol=1e-12,rtol=0)
print('All seven saved prediction means and intervals reproduced; no held-out outcomes read.')
