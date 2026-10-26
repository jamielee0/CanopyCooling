"""Advisor Section 7 Step 2: OLS on released 2023 pass estimates only."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

PREDICTORS = ('shortwave_W_m2', 'sin_solar_elevation')


def assemble_inputs(table, common):
    if len(table) != 23 or table[['city', 'orbit']].duplicated().any():
        raise ValueError('Step1 pass identity mismatch')
    held = table.loc[table.sample_role == 'other_year_prediction_inputs_only']
    if len(held) != 7 or held.cooling_K_per_10pp.notna().any():
        raise ValueError('Other-year outcome boundary failed')
    main = table.loc[table.sample_role == 'main_2023'].copy()
    if len(main) != 16 or main.city.value_counts().to_dict() != {'phoenix': 11, 'atlanta': 5}:
        raise ValueError('Wrong main sample')
    if not pd.to_datetime(main.acquisition_utc, utc=True).dt.year.eq(2023).all():
        raise ValueError('Only 2023 outcomes authorized')
    columns = ['city', 'orbit', 'local_date', 'acquisition_utc', 'apparent_solar_hour',
               'after_noon', 'shortwave_W_m2', 'sin_solar_elevation', 'solar_elevation_deg',
               'cooling_K_per_10pp', 'cooling_q025_8km', 'cooling_q975_8km']
    main = main[columns].rename(columns={'cooling_K_per_10pp': 'cooling',
                                        'cooling_q025_8km': 'q025', 'cooling_q975_8km': 'q975'})
    main['population'] = 'original'
    selected = common.loc[(common.city == 'phoenix') & (common.group_km == 8) &
                          (common.quantity == 'temperature')].copy()
    phx = main.loc[main.city == 'phoenix'].copy()
    if len(selected) != 11 or selected.orbit.duplicated().any() or set(selected.orbit) != set(phx.orbit):
        raise ValueError('Common-footprint membership mismatch')
    joined = phx.merge(selected, on=['city', 'orbit'], validate='one_to_one', suffixes=('', '_source'))
    if not joined.units.eq('K_per_10pp').all() or not joined.local_date.eq(joined.date).all():
        raise ValueError('Common-footprint units/date mismatch')
    if not np.allclose(joined.cooling, joined.original_point, atol=1e-10, rtol=0):
        raise ValueError('Original cooling sign/point does not reconcile')
    joined['cooling'], joined['q025'], joined['q975'] = joined.common_point, joined.common_q025, joined.common_q975
    joined['population'] = 'common'
    combined = pd.concat([main, joined[main.columns]], ignore_index=True)
    numeric = ['cooling', 'q025', 'q975', *PREDICTORS, 'after_noon', 'apparent_solar_hour']
    if not np.isfinite(combined[numeric].to_numpy(float)).all():
        raise ValueError('Missing/nonfinite model inputs; no silent row dropping')
    if not (combined.shortwave_W_m2 > 0).all():
        raise ValueError('Cooling/shortwave ratio requires positive shortwave')
    if not ((combined.q025 <= combined.cooling) & (combined.cooling <= combined.q975)).all():
        raise ValueError('Pass point outside supplied interval')
    if not combined.after_noon.eq((combined.apparent_solar_hour > 12).astype(int)).all():
        raise ValueError('After-noon definition differs')
    return combined.sort_values(['city', 'population', 'acquisition_utc']).reset_index(drop=True)


def fit_pass_model(rows, predictor):
    if predictor not in PREDICTORS:
        raise ValueError('Unspecified predictor')
    if rows.city.nunique() != 1 or rows.population.nunique() != 1:
        raise ValueError('Fit cities and populations separately')
    if rows.orbit.duplicated().any() or rows.local_date.duplicated().any():
        raise ValueError('Duplicate pass or date needs clarification before independent-pass OLS')
    if not np.isfinite(rows[['cooling', predictor, 'after_noon']].to_numpy(float)).all():
        raise ValueError('Missing values cannot be silently dropped')
    if set(rows.after_noon) != {0, 1}:
        raise ValueError('Both morning and afternoon required')
    x = np.column_stack([np.ones(len(rows)), rows[predictor], rows.after_noon])
    if len(rows) <= 3 or np.linalg.matrix_rank(x) != 3:
        raise ValueError('Insufficient residual degrees of freedom or rank')
    model = smf.ols(f'cooling ~ {predictor} + after_noon', data=rows, missing='raise').fit()
    if int(model.nobs) != len(rows):
        raise ValueError('Rows were dropped')
    return model


def arm_ratios(rows):
    if not np.isfinite(rows[['cooling', 'shortwave_W_m2']]).all().all() or not (rows.shortwave_W_m2 > 0).all():
        raise ValueError('Invalid ratio inputs')
    result = []
    for arm, r in rows.groupby('after_noon', sort=True):
        result.append({'after_noon': int(arm), 'arm': 'afternoon' if arm else 'morning',
                       'n_passes': len(r), 'mean_cooling_over_shortwave': float((r.cooling/r.shortwave_W_m2).mean()),
                       'mean_cooling_K_per_10pp': float(r.cooling.mean()),
                       'mean_shortwave_W_m2': float(r.shortwave_W_m2.mean())})
    return result
