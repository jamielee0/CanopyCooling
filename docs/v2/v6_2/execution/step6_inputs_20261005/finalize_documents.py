"""Record bounded Step6 completion, preserving every earlier execution record."""
import copy
import json
from pathlib import Path
import sys
import yaml

ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/"src"))
from v6_2_advance.run_step6_inputs import EXEC,PACKET,ACTIVE,dest,sha,write
ARCHIVE=ROOT/"docs/v2/v6_2/archive/before_step6_inputs_20261005"

class UniqueLoader(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):
 loader.flatten_mapping(node);result={}
 for k,v in node.value:
  key=loader.construct_object(k,deep=deep)
  if key in result:raise ValueError("Duplicate YAML key")
  result[key]=loader.construct_object(v,deep=deep)
 return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)

def main():
 verification=json.loads((EXEC/"verification.json").read_text());completion=json.loads(dest("completion.json").read_text())
 if verification['status']!='PASS' or completion['complete_rainfall_windows']!=48:raise ValueError('Incomplete verification')
 for rel in ACTIVE:
  if sha(ROOT/rel)!=sha(ARCHIVE/rel):raise ValueError('Active documentation changed since snapshot')
 statement=("The 5 October 2026 request to proceed with Step 6 authorized nonthermal conditions and comparison-input preparation. "
  "Completion is recorded in `docs/v2/v6_2/execution/step6_inputs_20261005/` and "
  "`deliverables/Step6_Conditions_2023_v6_2_20261005/`. All sixteen acquisitions now have exact-time HRRR temperature/dewpoint/wind and descriptive VPD. "
  "All48 hour-ended rainfall windows have complete totals: 47 MRMS and one separately labelled full-window Stage IV fallback for Phoenix July29 seven-day rainfall. "
  "The unavailable July24 15:00 UTC MRMS hour and its missing primary total are preserved; no product splicing or missing-value filling occurred. "
  "Rainfall windows end at the last completed hour before acquisition, with the subhour gap explicit. Sixteen geometry acquisition identities reconcile; "
  "eleven cached arrays and five view-only evidence records retain incomplete/unknown azimuth and unestablished modeled-cell coverage. "
  "The existing Phoenix five-date weights are unchanged, and Atlanta time support was audited independently. "
  "No sealed effect/model file, raw satellite thermal field, empirical time comparison, calibration effect grid or new inclusion cutoff was used. "
  "Step6 preparation is complete with these documented limits. Step7 uncertainty/calibration, effect review, coefficient release, scale ruling and expansion remain separate; "
  "new effects stay sealed and Reza's numerical tolerance remains pending.")
 p=ROOT/'AGENTS.md';p.write_text(p.read_text().replace('## Scope and preservation',statement+'\n\n## Scope and preservation',1))
 p=ROOT/'docs/v2/v6_2/pilot_plan_v6_2.md';text=p.read_text();i=text.index('\n');p.write_text(text[:i+1]+'\n## Current Step 6 status — 5 October 2026\n\n'+statement+'\n'+text[i+1:])
 p=ROOT/'docs/v2/v6_2/results_review_and_targeted_analysis_plan_20260930.md';text=p.read_text();i=text.index('\n')
 text=text[:i+1]+'\n**Latest status: Step6 nonthermal input preparation is complete; Step7 has not been executed.** '+statement+'\n'+text[i+1:]
 marker='### Step 6 Complete the inputs for the Phoenix window sensitivity'
 text=text.replace(marker,marker+'\n\n**Completed 5 October 2026 with explicit limits.** See the conditions packet and execution record above. The following specification remains the comparison definition; numerical cooling contrasts and their calibrated uncertainty are Step7 work.',1);p.write_text(text)
 p=ROOT/'docs/v2/v6_2/decision_log_v6_2.md';p.write_text(p.read_text()+'\n\n### 5 October 2026 — Step 6 nonthermal conditions completed\n\n'+statement+'\n\n'
  'Freeze exact acquisitions, domains, hourly matching, precipitation product/flags, accumulation windows and existing comparison weights before aggregation. '
  'Download only requested HRRR GRIB messages. Reconcile all20 cached hourly overlaps; exact temperature/domain agreement and inherited float32-decode VPD recovery distinguish representation rounding from changed meteorology. '
  'A specific rainfall fallback record freezes all168 Stage IV hours and its area-weighting before extraction; preserve the incomplete MRMS estimate rather than blending products. '
  'The different products can yield a seven-day fallback below the three-day primary estimate; this is labelled and not interpreted as nested rainfall. '
  'All fifteen rainfall inputs for the five comparison dates use MRMS. Twelve known-answer checks, 33 frozen input hashes and 2,200 downloaded source/index hashes pass. '
  'Public figures are visually reviewed. The ecCodes binding repair and final summary-column repair are implementation-only, with original code/freeze retained. '
  'The small date counts, weather differences, hourly rainfall endpoint and geometry limitations remain substantive; no professor approval or broader time interpretation is implied.\n')
 p=ROOT/'docs/v2/v6_2/prior_thermal_access.md';p.write_text(p.read_text()+'\n\n### 5 October 2026 — nonthermal Step 6 inputs\n\n'
  'User authorized Step6. Only non-effect columns from the existing pass table, cached nonthermal geometry evidence/arrays, and public HRRR/MRMS/Stage IV meteorological data were opened. '
  'No sealed model, coefficient, LST/M outcome column, satellite thermal raster or empirical time-effect file was opened. '
  'Calculated air temperature, dewpoint, wind, descriptive VPD, rainfall and centroid solar geometry are environmental inputs, not canopy effects. '
  'The Step6 execution freeze, geometry evidence list, download manifest and verification identify all sources and missing/fallback handling. '
  'The prior explicit sealing instruction and all historical effect-access records remain preserved.\n')
 p=ROOT/'docs/v2/v6_2/protocol_v6_2.yml';old=yaml.load(p.read_text(),Loader=UniqueLoader);text=p.read_text()
 replacement={
  'status: '+old['status']:'status: STEP6_INPUTS_COMPLETE_WITH_DOCUMENTED_LIMITS_2023',
  '  current_user_request: '+old['authority']['current_user_request']:'  current_user_request: 2026-10-05_user_requests_Step6_nonthermal_inputs_complete_new_effects_remain_sealed',
  '  current_pre_update_snapshot: '+old['authority']['current_pre_update_snapshot']:'  current_pre_update_snapshot: docs/v2/v6_2/archive/before_step6_inputs_20261005',
  '  Step5_internal_quadratic_executed: true':'  Step5_internal_quadratic_executed: true\n  Step6_nonthermal_inputs_executed: true',
  '    product_availability_and_exact_local_checksums: NOT_ACQUIRED_PRE_GATE_A_INVENTORY_GAP':'    product_availability_and_exact_local_checksums: BOUNDED_2023_STEP6_47_MRMS_WINDOWS_1_STAGE_IV_FALLBACK_SEE_step6_inputs_20261005',
  '- complete_linked_weather_and_calibrate_proposed_Phoenix_window_uncertainty':'- calibrate_proposed_Phoenix_window_uncertainty_after_completed_Step6_conditions',
 }
 for a,b in replacement.items():
  if text.count(a)!=1:raise ValueError('Protocol edit anchor changed')
  text=text.replace(a,b)
 section=dict(authority='User explicitly requested proceeding with Step6',status=completion['status'],
  execution_freeze='docs/v2/v6_2/execution/step6_inputs_20261005/execution_freeze.json',packet='deliverables/Step6_Conditions_2023_v6_2_20261005/README.md',
  year=2023,Phoenix_passes=11,Atlanta_passes=5,weather_complete=16,HRRR_hours=32,prior_hourly_weather_reconciled=20,
  rainfall_windows=48,primary_MRMS_windows=47,Stage_IV_whole_window_fallbacks=1,MRMS_hours=1872,MRMS_missing_hours=1,Stage_IV_hours=168,
  rainfall_window_end='floor exact acquisition UTC; report subhour lag',exact_subhourly_rainfall_totals=False,
  modeled_cell_geometry_crosswalk_complete=False,geometry_acquisition_ids_verified=16,geometry_cached_arrays_verified=11,
  view_only_summary_records=5,complete_joint_azimuth_passes=0,Phoenix_window_weights_unchanged=True,Atlanta_contrast_defined=False,
  known_answer_tests=12,frozen_inputs_verified=33,downloaded_files_verified=2200,
  sealed_model_or_effect_access=False,raw_satellite_thermal_access=False,empirical_time_contrast=False,
  simulation_effect_grid_selected=False,new_inclusion_cutoff=None,new_effect_display=False,scale_ruling=None,scope_expansion=False)
 tag='step6_conditions_inputs_20261005';text+='\n'+yaml.safe_dump({tag:section},sort_keys=False);p.write_text(text)
 current=yaml.load(text,Loader=UniqueLoader);normal=copy.deepcopy(current);normal.pop(tag)
 for k in ('status','next_actions_not_executed'):normal[k]=old[k]
 for k in ('current_user_request','current_pre_update_snapshot'):normal['authority'][k]=old['authority'][k]
 normal['control_boundary'].pop('Step6_nonthermal_inputs_executed')
 normal['products']['precipitation']['product_availability_and_exact_local_checksums']=old['products']['precipitation']['product_availability_and_exact_local_checksums']
 if normal!=old:raise ValueError('Unplanned protocol change')
 write(EXEC/'decision_record.json',dict(status=completion['status'],scope='Step6 nonthermal input preparation complete',
  weather_or_rainfall_used_to_change_sample=False,empirical_time_comparison_computed=False,Step7_executed=False,
  new_effects='SEALED_USER_REQUEST',scale_ruling=None,completion=completion))
 write(EXEC/'implementation_notes.json',dict(repairs=['ecCodes element lookup requires list, not ndarray; approved source-hash amendment applied to both manifest lists',
  'Final count accessed pandas product column with brackets to avoid method-name collision; existing numerical CSV values unchanged',
  'Public figure layout and Stage IV hatching/labels corrected during visual QA'],science_settings_changed=False,
  source_availability='MRMS single-hour absence retained; protocol Stage IV fallback computed for entire seven-day window'))
 write(EXEC/'documentation_verification.json',dict(status='PASS',unique_yaml_keys=True,unrelated_protocol_fields_unchanged=True,
  active_documents_archived=6,public_figures_visually_checked=3,new_effect_display=False,Step7_not_executed=True))

if __name__=='__main__':main()
