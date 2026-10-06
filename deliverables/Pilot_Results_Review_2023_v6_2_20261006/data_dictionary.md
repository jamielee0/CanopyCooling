# Released review data dictionary

## General conventions

The main sample is eleven Phoenix and five Atlanta passes, all 2023. `orbit`, `city`, acquisition timestamp and source run jointly identify an observation. Canopy uses fractions 0–1 internally; a +10 percentage-point contrast is +0.10. Positive cooling means lower modeled surface temperature with more canopy. K differences have the same numerical size as °C differences. These are conditional mixed-pixel associations, not measured tree-only temperatures or causal planting responses.

`point`, `q025`, `q975` and `SE` refer to a point estimate, spatial-bootstrap percentile endpoints and bootstrap sample SD. Group size is explicit. Intervals are individual/exploratory, not simultaneous or multiplicity-adjusted. Blank values indicate unavailable/inapplicable fields, never zero. A numerical difference interval excluding zero does not by itself establish practical importance or equivalence.

## Pass summary

`pilot_pass_summary.csv` contains sixteen rows with canonical Collection `002`, exact acquisition/solar time, original native-cell and block counts, whole-native-cell footprint area and canopy median. The cooling columns use original linear estimates and existing 8 km intervals. Equivalent and paired-difference columns use the matched Step3 diagnostics at the historical fixed reference. Weather and hour-ended rainfall are the completed Step6 descriptors, with the single Stage IV seven-day fallback explicitly identified. Weather values are modeled air conditions, not satellite surface temperatures.

`original_pass_results.csv` preserves the older full released export, including historical formatting and inherited weather fields. Use the concise pass summary and current conditions table for updated metadata and meteorology.

## Spatial sensitivities

`common_footprint_comparisons.csv` has 44 rows: eleven passes × two group sizes × temperature/flux. Prefixes `original`, `common` and `common_minus_original` identify the two populations and their paired change. `relative_change_percent` is a descriptive ratio of point changes to original points. Failure counts belong to each recorded joint comparison; no draw was replaced.

`fixed_registration_comparisons.csv` has 48 rows: 24 perturbations × two outcomes. Each is shifted-minus-unshifted on identical cells, using paired 1 km intervals. `dx`/`dy` are native-cell shift indices; one cell is 70 m. `available_registration_points.csv` has 88 rows and retains missing difference intervals because physical draw pairing was not verified for those changing samples. Its separate constituent intervals remain in the released source JSON files.

## Quadratic comparisons and curves

The historical endpoint table contains 96 temperature rows: sixteen passes × two group sizes × linear/quadratic/paired difference. The full contrast table additionally includes the other fixed candidate pairs, flux/equivalent diagnostics and explicit unsupported combinations. The raw polynomial terms are both changed at prediction endpoints. No pair was reselected after effect display.

The curve table retains each city's predictor-defined display range and lower reference. Its values are cumulative reference-to-target cooling differences, not marginal slopes or necessarily +10pp contrasts. Phoenix and Atlanta curve ranges/references differ. The historical 2.85%–12.85% contrast is therefore not the same quantity as the plotted curve's full endpoint difference.

## Fixed-date time comparisons

`phoenix_window_comparisons.csv` reproduces Step7 exactly. Positive point values mean stronger afternoon cooling; `drop_Aug06` and `drop_Aug23` retain the original month/arm target with the remaining August morning weighted 0.50. `influence_*` subtracts the full result from that deletion result. June11/June26/August11 deletions are unsupported and are not assigned numerical substitutes.

`joint_window_sensitivities.csv` contains forty rows from the recorded post-disclosure follow-up: five comparisons × two group sizes × four quantities. It uses the same physical-group draws across dates and the original/common/quadratic variants. `common_minus_original` and `quadratic_minus_original` are differences between time contrasts, not individual pass cooling changes. The original point matches Step7; fresh draw sequences produce slightly different finite-bootstrap endpoints. All rows are labeled `EXPLORATORY_POST_DISCLOSURE`.

`window_point_sensitivities.csv` records the initial arithmetic that motivated the follow-up. Its unavailable alternative intervals are superseded for uncertainty reporting by the joint follow-up table; the initial point record is preserved.

## Scale diagnostics

`paired_scale_diagnostics.csv` gives pass-level temperature cooling, converted energy cooling and their paired difference. `reference_sensitivity.csv` reports the predeclared temperature/emissivity reference grid; its ranges are sensitivity ranges, not confidence intervals. Time-level equivalents in the window tables average flux changes within arms before inversion and then compare arms. Pass-level discrepancies must not be substituted for the time-level diagnostic.

Temperature remains primary. No agreement margin or pass/fail ruling is supplied in these tables. The former display boundary was explicitly lifted; later tolerance selection must acknowledge the recorded effect access.
