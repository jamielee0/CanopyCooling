# Four items for review

Everything here is historical and non-thermal. No temperature or LST value was opened, no
holdout was selected, and no 2026 record was opened.

Start with `01_summary/Four_Items_Summary_2026-08-17.docx`. It is about four pages and covers
all four items, plus a section on why the city set went from five to four. Everything else is
here so you can check any number in it.

## 01_summary

The write-up. Sections 1 to 4 are the requested items. Section 5 explains the city-set change:
Los Angeles and Sacramento were removed by the frozen leaf-on screen, Miami could not be
evaluated by it, and Denver was added.

## 02_the_four_items

The packet itself, unchanged since it was approved on 16 August. Every file is bound by
SHA-256 in the decision record, and `independent_verification.json` recomputes all four
items from the raw CSVs using a script that imports no pipeline code.

| File | Item |
|---|---|
| `01_attrition_table.csv` | 1. Ten stages, 2,968 down to 102 |
| `02_pass_equivalent_formula.md` | 2. The formula and what it does not mean |
| `03_view_angle_threshold_results.csv` | 3. All five thresholds and why none was chosen |
| `04_within_city_high_demand_support.csv` | 4. Per city, both water metrics |
| `README.md` | Cover note with the headline numbers |
| `independent_verification.json` | Standalone recomputation and all file hashes |

## 03_figures

Real data only. Nothing in this folder is simulated.

| Figure | Shows |
|---|---|
| `F3_view_angle_threshold_counts.png` | Item 3. Passes per city at each threshold, plus which additions lack cloud and weather evidence |
| `F4_within_city_high_demand_support.png` | Item 4. High-demand wet and dry passes per city across all three water metrics and both windows |
| `S1_water_metric_distributions.png` | The rebuilt water axis: precipitation, days since rain, and the P minus ET0 sensitivity |
| `S2_season_leafon_screen.png` | The leaf-on screen that decided which seasons and cities qualified |

## 04_code

The code that produced the items, and the verifier.

| File | Produces |
|---|---|
| `hitl_gate1_reconciliation.py` | Items 1 and 2. Deduplication, attrition chain, pass-equivalent weights, weather join |
| `hitl_gate2_hydroclimate.py` | Item 4's water metrics. 30 and 60 day windows, correlations, support tables |
| `hitl_gate3_sampling.py` | Item 3. Threshold sequence, phenology screen, balance diagnostics |
| `run_v2_hitl_gate1.py`, `run_v2_hitl_gate2.py`, `run_v2_hitl_gate3.py` | Entry points for the three gates |
| `verify_v2_first_four_items.py` | Independent check. Imports none of the above |

To re-run the verifier from the repository root:

    python src/verify_v2_first_four_items.py

## 05_supporting_evidence

For checking specific claims in the summary.

| File | Answers |
|---|---|
| `method_notes.md` | Counting unit, view rule, the 413 to 219 derivation |
| `checks.json` | All eleven Gate-1 checks, including the accounting that sums to 2,968 |
| `attrition_breakdown.csv` | Attrition by city, year, month, and time stratum |
| `deduplication_summary.csv` | Tiles to observations, per city |
| `within_city_wet_dry_support.csv` | The 3x3 grid holding 0.553, 26.168, and the 155 |
| `pass_quality_219.csv` | Per-pass clear, cloud, and fill pixel counts |
| `hrrr_pass_hour_crosswalk.csv` | The 438 links and 25 shared hours |
| `archive_missing_31_audit.csv` | The 31 unavailable passes with proxy condition cells |
| `demand_predictor_correlations.csv` | Why P minus ET0 is coupled to demand |
| `high_demand_absolute_vpd_overlap.csv` | Continuous VPD overlap, not tercile membership |
| `g4_high_demand_city_audit.csv` | The four-city table in the summary |
| `review.md` | The Gate-2 write-up, including the rain-metric censoring problem |
| `MIAMI_EXCLUDED_SENSITIVITY/` | What every number becomes without Miami. The answer is that the stop cell does not change |

## Two open items

Usable tree and reference pixel counts per pass are missing. They need a frozen sampling
design and Gate 3 never selected one. They are recorded as unavailable rather than as zero.

The independent verification is a script, not a second person. Every check passes, but I
wrote the script.
