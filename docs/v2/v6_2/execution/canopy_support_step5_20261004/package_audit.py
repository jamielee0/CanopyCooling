"""Assemble public predictor-only documentation and retain source identities."""
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
PUB=ROOT/"outputs/v6_2/scientific/canopy_support_step5_20261004"
OUT=ROOT/"deliverables/Step5_Canopy_Support_2023_v6_2_20261004"


def meaning(name,table):
 basic={"city":"Frozen city identifier", "orbit":"Acquisition orbit as identifier text", "date":"2023 acquisition date",
 "month":"Calendar month", "apparent_solar_hour":"UTC/longitude/equation-of-time clock from the unchanged Step2 convention",
 "source_run_id":"Original paired native-cell run", "pair_id":"All15 prospectively recorded candidate contrasts, never selected by effects",
 "f0":"Lower raw-canopy endpoint, fraction", "f1":"Upper raw-canopy endpoint, f0+0.10", "halfwidth_fraction":"Descriptive endpoint halfwidth in canopy fraction; no inclusion threshold",
 "n_original_cells":"All unique original paired native cells", "n_original_blocks":"All occupied original 1km blocks",
 "spanning_blocks":"Blocks with observed min canopy ≤f0 and max ≥f1", "reference_cells":"All original cells in spanning blocks; models are not restricted here",
 "reference_whole_native_area_km2":"reference_cells×0.0049 km², whole native footprints in native UTM projection; not city-clipped area",
 "reference_cell_fraction":"Reference cells / original cells", "endpoint_status":"BLOCK_SPANNED or NO_BLOCK_SPANS_BOTH_ENDPOINTS; neighbourhood proximity alone is insufficient",
 "blocks_with_both_neighbourhoods":"Blocks containing at least one observation in each endpoint neighbourhood; may differ from exact spanning blocks",
 "cells_in_both_neighbourhoods":"Cells counted in both closed bands when they touch; explicitly reported to avoid treating counts as disjoint",
 "endpoint":"Lower or upper endpoint of historical contrast", "variable":"One of six unchanged context controls", "unit":"Fraction or m as appropriate to control",
 "model":"Linear (f) or protected quadratic (f,f²) predictor design; no outcome fit", "status":"Design estimability or descriptive-distance availability, not an effect/overlap acceptance verdict",
 "n_cells":"All original paired native observations used by design", "n_blocks":"Original occupied 1km intercept blocks",
 "n_parameters":"Retained slope/context columns excluding block intercepts", "rank":"Rank of column-normalized block-centered design at frozen tolerance 1e-10",
 "residual_dof":"n_cells − n_blocks − n_parameters", "protected_terms":"Mandatory canopy basis columns; one linear, two quadratic",
 "removed_context_terms":"JSON array of context dependencies removed before canopy rank check under inherited rule; no protected canopy term removed",
 "scaled_design_condition":"Largest / smallest singular value of column-normalized within-block design; descriptive numerical conditioning",
 "scaled_design_smallest_singular":"Smallest singular value of that normalized design",
 "partial_canopy_term":"raw_f for linear or raw_f_squared for quadratic",
 "partial_canopy_information":"Sum squared residual of designated canopy term after all other retained columns; fraction² for f or fraction⁴ for f²; no outcome information",
 "partial_canopy_effective_information_blocks":"Inverse sum squared block shares of partial canopy information; not independent days",
 "maximum_partial_canopy_information_share":"Largest block share of partial canopy information",
 "top_five_partial_canopy_information_share":"Sum of five largest such shares",
 "group_km":"1km or8km whole physical resampling groups, retaining original 1km intercepts",
 "groups":"Number of occupied physical resampling groups", "requested":"1000 design-only multinomial draws per pass/group configuration",
 "linear_estimable":"Draws whose frozen linear Gram matrix retains full rank at 1e-10",
 "quadratic_estimable":"Draws whose frozen quadratic Gram matrix retains full rank at 1e-10",
 "paired_estimable":"Draws estimable in both designs using identical physical multiplicities", "paired_failed":"Requested minus paired_estimable; no replacement",
 "draw_multiplicity_sha256":"Hash of exact ordered int64 multiplicity vectors for reproducibility",
 "query_cells":"Up to2000 uniformly sampled cells per pass/endpoint/width, without replacement",
 "other_city_reference_cells":"Equal-size other-city reference pool, deduplicated by physical cell_id; max5000",
 }
 if name in basic:return basic[name]
 if name in ("n","min","p05","p25","median","p75","p95","max","mean","sd"):
  if name=="n":return "Number of cell values entering distribution; zero is preserved"
  unit="dimensionless standardized six-control Euclidean distance" if table=="cross_city_context_distances.csv" else "the named control's units (fraction; elevation/distance_to_water in m)"
  return f"{name} of {unit}; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero"
 for side in ("lower","upper"):
  if name.startswith(side+"_"):
   tail=name[len(side)+1:]
   defs={"band_lo":"clipped lower edge of closed endpoint neighbourhood", "band_hi":"clipped upper edge of closed endpoint neighbourhood",
    "cells":"all original cells in neighbourhood", "blocks":"blocks represented by neighbourhood cells", "cells_in_reference":"neighbourhood cells in exact-spanning reference blocks",
    "fraction":"neighbourhood cells / original cells", "density_per_fraction":"neighbourhood fraction divided by actual clipped band width"}
   if tail in defs:return side.capitalize()+" endpoint: "+defs[tail]
 raise ValueError("Missing dictionary definition: "+name)


def run():
 matrices=json.loads((PUB/"public_table_matrices.json").read_text())
 lines=["# Step 5 predictor support dictionary","","All tables are predictor-only. No outcome, coefficient, effect point, confidence endpoint or new inclusion decision is present. Empty fields denote unassessable/empty support; counts of zero remain zero. Candidate pairs, neighbourhoods and resampling configurations repeat observations and are not additional temporal samples.",""]
 dictionary={}
 for table,data in matrices.items():
  definitions=[dict(column=k,meaning=meaning(k,table)) for k in data["headers"]];dictionary[table]=definitions
  lines += ["## "+table,"","| Column | Meaning |","| --- | --- |"]
  lines += [f"| `{r['column']}` | {r['meaning']} |" for r in definitions];lines += [""]
 (OUT/"data_dictionary.md").write_text("\n".join(lines)+"\n")
 (OUT/"data_dictionary.json").write_text(json.dumps(dictionary,indent=2)+"\n")
 for stem in ("historical_endpoint_support","candidate_pair_block_support","quadratic_design_rank_support","cross_city_context_support"):
  for ext in ("png","pdf"):shutil.copy2(PUB/f"{stem}.{ext}",OUT/f"{stem}.{ext}")
 for name in ("completion.json","control_information_support.json","within_block_canopy_span.json","cross_city_reference_sampling.json","failures.json"):
  shutil.copy2(PUB/name,OUT/name)
 endpoint=matrices["endpoint_support.csv"];rows=[dict(zip(endpoint["headers"],r)) for r in endpoint["rows"]]
 historical=[r for r in rows if r["pair_id"]=="historical" and r["halfwidth_fraction"]==.01]
 summaries={}
 for city in ("phoenix","atlanta"):
  r=[x for x in historical if x["city"]==city]
  fields=("spanning_blocks","reference_cell_fraction","lower_fraction","upper_fraction")
  summaries[city]={field:[min(x[field] for x in r),max(x[field] for x in r)] for field in fields}
 coverage=[]
 for city in ("phoenix","atlanta"):
  for month in (6,7,8,9):
   for window in ("morning_9.5_to_11.5","afternoon_15_to_18","other_observed_time"):
    selected=[]
    for r in historical:
     h=r["apparent_solar_hour"];w="morning_9.5_to_11.5" if 9.5<=h<=11.5 else "afternoon_15_to_18" if 15<=h<=18 else "other_observed_time"
     if r["city"]==city and r["month"]==month and w==window:selected.append(r)
    coverage.append(dict(city=city,month=month,window=window,passes=len(selected),orbits=[r["orbit"] for r in selected],spanning_blocks=[r["spanning_blocks"] for r in selected]))
 (OUT/"support_summary.json").write_text(json.dumps(dict(historical_pair=summaries,all16_designs_estimable=True,all32000_design_draws_estimable=True,
  figures_are_nonthermal=True,candidate_selection_by_outcomes=False,city_ranking_claim=False,fit_scope="pending clarification; current Step4 hold preserved",outcome_fits=0),indent=2)+"\n")
 (OUT/"month_time_support.json").write_text(json.dumps(dict(rule="Existing descriptive morning/afternoon windows; no time comparison or new inclusion filter",rows=coverage),indent=2)+"\n")
 print(json.dumps(dict(public_dictionary_columns=sum(len(x) for x in dictionary.values()),support_summary=summaries),indent=2))


if __name__=="__main__":run()
