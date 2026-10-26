from pathlib import Path
import json
import hashlib
import yaml
R=Path('/Users/jmlee/Documents/TreeProject')
E=R/'docs/v2/v6_2/execution/advisor_step1_20261026'
c=json.loads((E/'completion.json').read_text())
v=json.loads((E/'independent_verification.json').read_text())
assert c['status']=='STEP1_INPUTS_COMPLETE' and v['status']=='PASS'
heading='## Current advisor Step 1 — 26 October 2026'
entry='''The user authorized the entire Section 7 Step 1 of Reza's latest review and requested clarification before workarounds. This is a new advisor sequence, distinct from the earlier October review steps. The 23-pass nonthermal input table is complete: sixteen existing 2023 passes plus seven Phoenix passes from 2019/2024/2025. Exact checksum-bound ECO_L1B_GEO.002 metadata gives 38 Best and 2 Good source scenes; the historical census accepted both categories. HRRR CONUS wrfsfcf00 shortwave/weather and solar inputs cover all 23 rows and 46 bracketing hours. Shortwave uses the advisor's cosine-normalized interpolation. The sixteen original 2023 table rows retain every inherited field exactly.

Two explicit user decisions control this step: recover exact GEO flags rather than treating pooled Best/Good labels as exact Good, and retain model/selection-table acquisition times for four passes whose older geometry bindings are about 52 seconds later. Scene timestamps, both pass times, discrepancies and source hashes are preserved. No source substitution, new inclusion rule or actual image-alignment conclusion follows from these metadata checks.

The seven other-year cooling estimates remain unopened and their outcome fields blank. Only their nonthermal inputs were prepared. No new model was fitted. Further synthetic calibration, temperature–energy agreement work and quadratic analysis are stopped under the latest review. Step 2 models/figures, Step 3 predictions and the committed note before other-year outcome access remain subsequent work; this Step 1 request does not execute or authorize their release. No commit, push or external sending occurred. All historical results and access records are preserved.

Execution: `docs/v2/v6_2/execution/advisor_step1_20261026/`. Packet: `deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/`. The earlier entries below remain history; this entry controls the current bounded work.
'''
for p in [R/'AGENTS.md',R/'docs/v2/v6_2/pilot_plan_v6_2.md']:
 s=p.read_text(); assert heading not in s
 first,rest=s.split('\n',1); p.write_text(first+'\n\n'+heading+'\n\n'+entry+'\n'+rest.lstrip('\n'))
p=R/'docs/v2/v6_2/decision_log_v6_2.md'
s=p.read_text(); marker='### 26 October 2026 — advisor Section 7 Step 1 inputs'
assert marker not in s
p.write_text(s+'\n\n'+marker+'\n\n'+entry+'\nValidation: 21 network-free known-answer/boundary tests passed. An independent output audit checks all 23 radiation calculations, 230 hourly field records and hashes, 32 reproduced historical hourly cell arrays, exact preservation of all sixteen source rows, 40 scene categories, leap-year handling, four approved timestamp differences and blank other-year outcomes. The earlier active documents and source registry are archived under `archive/before_advisor_step1_20261026/`.\n')
p=R/'docs/v2/v6_2/prior_thermal_access.md'
s=p.read_text(); assert marker not in s
p.write_text(s+'\n\n'+marker+'\n\nThe new pass table copies only the already released sixteen 2023 result rows and adds nonthermal inputs. Seven other-year metadata rows were read from the selection and public support tables; their cooling estimates, model arrays and native thermal values were not opened. LST filenames were listed only to reconcile source-scene membership; raster bytes were not read or hashed. ECO_L1B_GEO.002 metadata and HRRR meteorology/radiation are the new inputs accessed. No new fit or outcome disclosure occurred. The other-year access boundary remains the dated, committed Step 3 prediction note followed by separately authorized execution. Full records: `execution/advisor_step1_20261026/`.\n')
p=R/'docs/v2/v6_2/protocol_v6_2.yml'
s=p.read_text(); assert '\nadvisor_step1_20261026:' not in s
s=s.replace("updated_on: '2026-10-06'","updated_on: '2026-10-26'",1)
s=s.replace('status: CURRENT_2023_EFFECTS_RELEASED_REVIEW_COMPLETE_SCALE_MARGIN_PENDING','status: ADVISOR_STEP1_NONTHERMAL_INPUTS_COMPLETE_OTHER_YEAR_OUTCOMES_UNOPENED',1)
s=s.replace('  current_user_request: 2026-10-06_user_lifts_current2023_sealing_and_requests_next_steps_release_review_complete','  current_user_request: 2026-10-26_entire_advisor_section7_step1_with_two_explicit_metadata_clarifications',1)
s=s.replace('  current_pre_update_snapshot: docs/v2/v6_2/archive/before_results_release_20261006','  current_pre_update_snapshot: docs/v2/v6_2/archive/before_advisor_step1_20261026',1)
section={'advisor_step1_20261026':{
 'status':'COMPLETE_INPUTS_ONLY', 'sequence':'Section 7 of latest advisor review; distinct from historical review Steps 1–7',
 'execution_record':'docs/v2/v6_2/execution/advisor_step1_20261026/',
 'packet':'deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/',
 'passes':{'main_2023':16,'other_year_phoenix_nonthermal_only':7},
 'geolocation':{'product':'ECO_L1B_GEO.002','field':'L1GEOMetadata/GeolocationAccuracyQA','source_scenes':40,'best':38,'good':2,'census_usable':['best','good'],'exact_cached_metadata_recovery_user_approved':True,'actual_alignment_verified':False},
 'weather':{'product':'HRRR CONUS wrfsfcf00 analysis','hours':46,'shortwave_shortName':'sdswrf','shortwave_units':'W m**-2','domain':'unchanged frozen Census urban-area grid-center support','shortwave_interpolation':'interpolate hourly sw/cos(zenith), multiply acquisition cosine; use other ratio if one hourly cosine <0.1; stop if both below','existing_2023_weather_reproduced':True},
 'timing':{'convention':'existing model/selection-table acquisition time','approved_discrepancy_orbits':[6281,33623,40111,40376],'individual_scene_times_preserved':True,'leap_year_length_explicit':True},
 'all_original_2023_fields_preserved':True,'new_fits':0,'seven_other_year_outcomes_opened':False,
 'further_synthetic_calibration':'STOPPED','further_temperature_energy_agreement':'STOPPED','further_quadratic_analysis':'STOPPED',
 'step2_models_executed':False,'step3_predictions_executed':False,'other_year_release_requires':'dated committed Step3 prediction note before outcome access and separately authorized execution',
 'commit_push_or_external_send_authorized_by_step1':False}}
s+='\n'+yaml.safe_dump(section,sort_keys=False,allow_unicode=True); p.write_text(s)
p=R/'deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/README.md'
s=p.read_text().replace('Completion and verification are recorded in `completion.json` and `../../docs/v2/v6_2/execution/advisor_step1_20261026/independent_verification.json` when execution finishes.','Step 1 is complete. Completion and verification are recorded in `completion.json` and `../../docs/v2/v6_2/execution/advisor_step1_20261026/independent_verification.json`.')
p.write_text(s)
print('Updated bounded authority, protocol, plan, decision log, access record and packet status.')
