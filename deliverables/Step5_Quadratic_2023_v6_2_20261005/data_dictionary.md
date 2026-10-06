# Step 5 quadratic sensitivity data dictionary

## Precision table

Each row identifies a city, orbit, acquisition date, candidate canopy pair (`pair_id`, `f0`, `f1`), spatial group size (`group_km`), model and quantity. Canopy values use fractions 0–1; all endpoint pairs differ by 0.10. Models are `linear`, `quadratic` and the paired `quadratic_minus_linear` difference.

Quantities are temperature cooling (K), emitted-flux reduction (W/m2), the exact fixed-reference temperature equivalent (K), and temperature cooling minus that equivalent (K). `SE` is the sample standard deviation across estimable matched spatial draws. `width95` is the 97.5th minus 2.5th percentile; the endpoints themselves remain sealed. `requested`, `estimable` and `failed` count draws for that quantity. An invalid transformation would be reported separately without suppressing the original temperature/flux calculation. All quantities in this run have 1,000 estimable draws per configuration.

`support_status=BLOCK_RANGE_ONLY` means at least one original block spans the two endpoints. It does not establish conditional covariate overlap or adequate density. Pairs with no spanning block appear in the support table and sealed missing-result ledger, not in the precision table. `effect_status=SEALED_USER_REQUEST` is mandatory. No point estimate, coefficient, interval endpoint, sign, p-value or significance indicator is permitted in this table.

## Retained support

Columns reproduce the [preceding predictor audit](../Step5_Canopy_Support_2023_v6_2_20261004/data_dictionary.md): city/orbit/date; candidate endpoints; neighbourhood halfwidth; exact spanning blocks; reference cells, whole-native-cell area and fraction; lower/upper neighbourhood limits, counts, block counts, reference counts, fractions and densities; blocks containing both neighbourhoods; and shared-band cells. Reference cells are all original cells in spanning blocks. The model still uses the complete original pass population. Cell area uses the established 70 m native-cell footprint (0.0049 km²), not city-clipped area.

## Resampling

`groups` counts occupied physical resampling groups; `requested` is 1,000. Estimability is reported separately for linear, quadratic and jointly estimable draws. Failed indices are zero-based and never replaced. `draw_multiplicity_sha256` hashes ordered little-endian 64-bit integer multiplicity vectors, using sorted physical groups. Hashes exactly match the frozen predictor-only audit; they establish actual draw correspondence, not merely identical random seeds.

## Fit diagnostics

`n_cells` and `n_blocks` describe the unchanged original pass. `linear_rank=7` and `quadratic_rank=8` count canopy terms plus six controls after removing block means; block intercepts are additional nuisance parameters. `controls_retained=6` records that none was dropped. `original_linear_recovered` refers to the temperature slope only. Paired draw totals sum the 1 km and 8 km configurations. `supported_candidate_pairs` counts block-spanned pairs, without an adequacy assertion. Source/execution hashes bind the record to its frozen inputs. Elapsed time is runtime metadata.

## Sealed comparison tables

The finite-contrast table adds `point`, `q025`, `q975`, uncertainty and estimability status to the public identifying fields. Unsupported combinations carry `NOT_ESTIMATED_NO_REFERENCE_BLOCKS` with no numerical effects. Positive point values denote cooling/reduced flux; `quadratic_minus_linear` subtracts the linear cooling estimate from the quadratic estimate. The curve table substitutes a target canopy fraction and city-specific reference for the +10pp pair, retaining spanning-block counts, grouping, model and quantity. Curves describe reference-to-target differences, not marginal derivatives. Their intervals are pointwise. These two tables remain sealed and are not part of the public packet.
