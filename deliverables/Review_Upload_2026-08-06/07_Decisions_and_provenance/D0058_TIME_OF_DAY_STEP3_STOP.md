# D0058 — time-of-day Step 3 stop

## Outcome

The approved time-of-day-only branch does not pass its prethermal simulation gate. The canonical result is `STOP_TIME_OF_DAY_ONLY_STEP3`; it does not authorize Task 2 or any LST/thermal access.

The earlier demand-by-antecedent-dryness result remains a separate, immutable `STOP`: the low-demand/dry corner contains 0.553 expected pass-equivalents against the frozen minimum of 10.

## Empirical support carried into the simulation

| Quantity | Value |
|---|---:|
| All retained near-nadir physical passes | 219 |
| All-stratum expected pass-equivalents | 159.087 |
| Primary 10–12 versus 16–18 physical passes | 102 |
| Primary expected pass-equivalents | 72.689 |
| Full-panel planning floor | 72 |
| Planning floor after the preplanned Minneapolis–St. Paul exclusion | 56 |
| Worst permitted non-Phoenix exclusion floor | 54 |

## Gate results

| Required check | Result | Threshold | Verdict |
|---|---:|---:|---|
| Full-panel power for a 1.50 K contrast | 0.110 | at least 0.800 | Fail |
| Power after excluding Atlanta | 0.100 | at least 0.800 | Fail |
| Power after excluding Los Angeles | 0.145 | at least 0.800 | Fail |
| Power after excluding Miami | 0.140 | at least 0.800 | Fail |
| Power after excluding Minneapolis–St. Paul | 0.100 | at least 0.800 | Fail |
| Pooled zero-effect rejection rate | 0.090 | at most 0.100 and Wilson interval must contain 0.050 | Fail |
| Pass-block interval coverage | 0.983 | at least 0.900 and interval contains 0.950 | Pass |
| Pass-block minus naive-row coverage | 0.467 | at least 0.100 | Pass |
| Large-sample coefficient bias, all three effects | 0.024–0.087 K | at most 0.200 K | Pass |

The gate passed 8 of 11 required checks. All four permitted leave-one-city-out branches failed power, so the conclusion is not caused by the planned holdout choice.

## Why power is low

The primary stratum contrast is nearly determined by the adjustment variables in the observed pass template. Regressing the late-afternoon indicator on city, demand, antecedent dryness, solar zenith, solar-azimuth sine/cosine, and day of year gives R² 0.9942, equivalent to a variance-inflation factor of 173.4. The late-afternoon indicator correlates 0.937 with solar zenith and -0.968 with solar-azimuth sine.

This is an identification problem, not a pixel-count problem: adding more rows within the same pass cannot create independent time/geometry support. Even the 800-pass simulation scenario reaches only 0.395 power for a 1.50 K contrast and 0.730 for a 2.25 K contrast.

## Consequence

- Keep the original demand × dryness `STOP` and the D0056 time-of-day `STOP` as distinct findings.
- Do not create a scoped Task-1 PASS.
- Do not select or open the Minneapolis–St. Paul holdout.
- Do not run Task 2, open LST/thermal rasters, or open the 2026 season.
- Any future empirical continuation needs a newly approved design or additional observations with independent time/solar-geometry support. Dropping controls or relaxing thresholds after seeing this result would not be an acceptable remediation.

## Bound evidence

- Gate: `data/processed/v2/task1/step3_time_of_day_only_D0056/step3_time_of_day_gate.json` (`098e1a403a89de265b44d3e679d659731d84ea775ee124d046cb0c67fd6101dd`)
- Run record: `data/processed/v2/task1/step3_time_of_day_only_D0056/run_record.json` (`d9f499a256425fe85cdc542d9a1e97781172a0722741efba1712c064312b03bc`)
- Required checks: `data/processed/v2/task1/step3_time_of_day_only_D0056/tables/step3_time_of_day_checks.csv` (`86470c9dd25b60f14858cba621873fc27571fb2a8af23bc5007d4d7986424f40`)

No LST/thermal value, holdout outcome, or 2026 observation was opened.
