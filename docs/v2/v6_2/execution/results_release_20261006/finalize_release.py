"""Amend current access policy under explicit user authority; retain past records."""
import copy,json,sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
EXEC=Path(__file__).resolve().parent;ARCHIVE=ROOT/'docs/v2/v6_2/archive/before_results_release_20261006'
PACKET=ROOT/'deliverables/Pilot_Results_Review_2023_v6_2_20261006'
def sha(p):
 import hashlib
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
class UniqueLoader(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):
 loader.flatten_mapping(node);out={}
 for k,v in node.value:
  key=loader.construct_object(k,deep=deep)
  if key in out:raise ValueError('Duplicate YAML key')
  out[key]=loader.construct_object(v,deep=deep)
 return out
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)

def main():
 if json.loads((EXEC/'verification.json').read_text())['status']!='PASS':raise ValueError('Incomplete result verification')
 snap=json.loads((ARCHIVE/'snapshot.json').read_text())
 for r in snap['files']:
  if sha(ROOT/r['path'])!=r['sha256'] or sha(ARCHIVE/r['path'])!=r['sha256']:raise ValueError('Unrelated active-file change since snapshot')
 statement=("On 6 October 2026 the user explicitly said ‘lets not keep it sealed then? Can you do the next steps?’ This supersedes the previous display restriction for the current sixteen-pass2023 pilot, including review before a scale tolerance is supplied. "
  "The current release and completed synthesis are recorded in `docs/v2/v6_2/execution/results_release_20261006/` and `deliverables/Pilot_Results_Review_2023_v6_2_20261006/`. "
  "Previously deferred spatial, quadratic and fixed-date effect/figure reviews are complete. All161 historical result files remain unchanged and85 source artifacts have released copies. "
  "A separately frozen, explicitly post-disclosure joint-uncertainty follow-up reconstructed fifteen existing points for the five Phoenix dates across original linear, common-footprint linear and original quadratic variants. "
  "Its combined8km temperature contrasts are −0.325, −0.106 and −0.433 K/+10pp respectively; all three conditional spatial intervals exclude zero, while the magnitudes differ. "
  "Four coarse-group joint draws fail only for the common footprint because sampled bare-cover variation is absent; none is replaced and all six controls are retained. "
  "The original population/linear model and temperature-primary hierarchy remain unchanged. Current2023 effect display no longer waits for Reza's tolerance. "
  "A formal practical scale-agreement ruling still requires a recorded numerical margin and paired uncertainty; any later margin must acknowledge that these effects have been seen. "
  "No general summer/causal time effect, new inclusion cutoff, other-year release, city/year expansion or external sending is authorized by this review. "
  "Earlier sealing/deferred-review statements below are historical records and are superseded within this release scope.")
 p=ROOT/'AGENTS.md';s=p.read_text();s=s.replace('## Current authority\n','## Current authority\n\n'+statement+'\n',1)
 replacements={
 'The user explicitly requires coefficients to remain sealed and the final scale ruling to wait for Reza’s numerical tolerance.':'The current2023 pilot effects are authorized for exploratory display under the 6 October release record. The formal scale ruling still waits for a recorded numerical tolerance; other-year results retain their separate access scope.',
 'Freeze the time model, references and precision aggregation before computing comparisons; record the scale tolerance before coefficient display.':'Freeze the time model, references and precision aggregation before computing comparisons. Current2023 review display is authorized without a prior scale tolerance; record the numerical margin before a formal agreement ruling and acknowledge post-disclosure selection.',
 'Preserve coefficient sealing and prior thermal-access records; publish only permitted precision diagnostics before release.':'Preserve historical private originals and prior thermal-access records; display current2023 effects within the recorded release scope and keep other outputs within their own access boundaries.',
 }
 for a,b in replacements.items():
  if s.count(a)!=1:raise ValueError('AGENTS access-policy anchor changed')
  s=s.replace(a,b)
 p.write_text(s)
 p=ROOT/'docs/v2/v6_2/pilot_plan_v6_2.md';s=p.read_text();i=s.index('\n');p.write_text(s[:i+1]+'\n## Current released review — 6 October 2026\n\n'+statement+'\n'+s[i+1:])
 p=ROOT/'docs/v2/v6_2/results_review_and_targeted_analysis_plan_20260930.md';s=p.read_text();i=s.index('\n');p.write_text(s[:i+1]+'\n**Current status: the user-authorized 2023 effect release and integrated pilot review are complete.** '+statement+'\n'+s[i+1:])
 p=ROOT/'docs/v2/v6_2/decision_log_v6_2.md';p.write_text(p.read_text()+'\n\n### 6 October 2026 — current2023 effects released and reviewed\n\n'+statement+'\n\n'
  'Record explicit authorization before effect access and archive the six active documents. The original file labels/permissions and earlier disclosure records remain unchanged. '
  'Review all five spatial/scale figure families, all32 quadratic figures and both fixed-date figures; publish readable release figures and reconcile source/table values. '
  'The original five-date temperature contrast is −0.324990 with Step7 8km interval [−0.390766,−0.262091]. Common-footprint effects are lower in all eleven Phoenix passes, and fixed-support alignment perturbations change individual estimates by −0.271 to+0.179 K/+10pp. '
  'Quadratic effects at the historical endpoints differ from linear estimates, with ten of sixteen individual paired intervals excluding zero; no multiplicity-adjusted model-selection claim or automatic model replacement is made. '
  'The original time energy-equivalent diagnostic is −0.548801 K/+10pp, giving a paired temperature-minus-equivalent discrepancy +0.223811 [0.182214,0.267731]; temperature stays primary and practical agreement remains undecided.\n\n'
  'After these existing points were viewed, a limited follow-up prospectively recorded the same five dates, three old model/population variants, old endpoints/controls and shared1km/8km group draws. '
  'It resolves the missing joint uncertainty for the footprint/model time sensitivities without treating unrelated archived draw indices as paired. '
  'The quadratic reference-basis rotation is algebraically identical to raw f,f²; all fifteen prior paired points were recovered. '
  'Common-minus-original time change is +0.219311 [0.162050,0.277575]; quadratic-minus-original change is −0.108328 [−0.153932,−0.071701] at8km. '
  'All1km draws and996/1000 complete8km draws are estimable. The4 failed coarse draws match the absence of the sparse common bare control; no rescue changes are applied. '
  'Four new known-answer checks and independent interval/identity reconstruction passed. This follow-up is exploratory after disclosure, not blinded confirmation.\n\n'
  'Retain the baseline and report sensitivity beside the selected-date result. No general summer interval is adopted, no true registration error or named-neighborhood mechanism is established, and no new city ranking is inferred. '
  'The bounded pilot report, methods/captions and next-decision note are complete. Further processing needs a defined population/target and its own scope; nothing is sent to others.\n')
 p=ROOT/'docs/v2/v6_2/prior_thermal_access.md';p.write_text(p.read_text()+'\n\n### 6 October 2026 — explicit exploratory release and post-disclosure follow-up\n\n'
  'The user explicitly lifted the current2023 sealing instruction. Authorization was recorded before opening numerical effects. The assistant read and interpreted the Step3 spatial/paired-scale/reference summaries, Step5 quadratic finite contrasts and curves, and Step7 fixed-date/monthly/deletion effects, and visually reviewed all39 corresponding PNG figures. '
  'Historical source artifacts retain checksums and private filenames; released copies and current labels distinguish provenance from the new display permission. The initial inventory hashed161 result files without decoding all model arrays. '
  'A subsequent recorded follow-up read only existing2023 Phoenix native frames, reconstructed old linear/common/quadratic models and computed matched sensitivity intervals. '
  'Its common-mask rank diagnosis used predictor-only data. It is explicitly post-disclosure. No new raw thermal rasters, other-year results or old original time-contrast files were opened, and no external communication occurred. '
  'The tolerance remains unset; any later margin is chosen after effect access and cannot be presented as globally blinded or pre-disclosure.\n')
 p=ROOT/'docs/v2/v6_2/protocol_v6_2.yml';old=yaml.load(p.read_text(),Loader=UniqueLoader);s=p.read_text()
 edits={
  "updated_on: '2026-10-05'":"updated_on: '2026-10-06'",
  'status: '+old['status']:'status: CURRENT_2023_EFFECTS_RELEASED_REVIEW_COMPLETE_SCALE_MARGIN_PENDING',
  '  current_user_request: '+old['authority']['current_user_request']:'  current_user_request: 2026-10-06_user_lifts_current2023_sealing_and_requests_next_steps_release_review_complete',
  '  current_pre_update_snapshot: '+old['authority']['current_pre_update_snapshot']:'  current_pre_update_snapshot: docs/v2/v6_2/archive/before_results_release_20261006',
  '  coefficient_unsealing_authorized_by_this_update: '+old['control_boundary']['coefficient_unsealing_authorized_by_this_update']:'  coefficient_unsealing_authorized_by_this_update: current16pass2023_review_and_recorded_followup_authorized_without_prior_tolerance; other_year_scope_unchanged',
  '  point_estimates: '+old['stage_1']['point_estimates']:'  point_estimates: current2023_review_disclosed_20261006; historical_private_storage_preserved; no_global_blindness_claim',
  '  tolerance_status: '+old['scale_decision']['tolerance_status']:'  tolerance_status: PENDING_REZA_FORMAL_RULING_ONLY; current2023_effects_disclosed_20261006; later_margin_is_post_disclosure',
 }
 for a,b in edits.items():
  if s.count(a)!=1:raise ValueError('Protocol policy anchor changed')
  s=s.replace(a,b)
 # Replace the current work list, not historical step execution records.
 start=s.index('next_actions_not_executed:\n');end=s.index('implementation:\n',start)
 next_steps=['define_intended_population_and_investigate_alignment_composition_mechanisms','record_post_disclosure_scale_margin_before_formal_agreement_ruling',
  'prospectively_scope_additional_independent_date_metadata_audit_before_acquisition_or_city_year_expansion']
 s=s[:start]+yaml.safe_dump({'next_actions_not_executed':next_steps},sort_keys=False)+s[end:]
 key='  current_release_sequence:\n';start=s.index(key);end=s.index('\nscale_decision:',start)
 seq=['current2023_effect_display_and_review_authorized_20261006_without_prior_scale_tolerance',
      'preserve_old_sources_and_disclosure_history; label_post_disclosure_followup',
      'formal_scale_agreement_requires_later_recorded_margin_and_paired_uncertainty',
      'no_automatic_model_population_or_energy_promotion; expansion_requires_own_scope']
 seq_text=yaml.safe_dump({'current_release_sequence':seq},sort_keys=False)
 s=s[:start]+''.join('  '+line+'\n' for line in seq_text.rstrip().splitlines())+s[end:]
 section=dict(authority="User explicitly lifts current2023 sealing and asks next steps",status='RELEASED_AND_REVIEWED',
  scope='docs/v2/v6_2/execution/results_release_20261006/authorization.json',
  report='deliverables/Pilot_Results_Review_2023_v6_2_20261006/README.md',year=2023,Phoenix_passes=11,Atlanta_passes=5,
  new_effect_display_authorized=True,display_before_tolerance_authorized=True,later_margin_post_disclosure=True,
  temperature_remains_primary=True,formal_scale_agreement=None,scale_tolerance=None,
  historical_result_files_preserved=161,released_source_copies=85,archived_effect_figures_visually_reviewed=39,
  original_population_linear_model_retained=True,post_disclosure_followup=True,new_model_specifications=False,
  followup_existing_points_reconstructed=15,followup_group_km=[1,8],followup_replicates_each=1000,
  followup_complete_joint_draws=1996,followup_common_failed_joint_draws=4,followup_failed_draws_replaced=False,
  followup_known_answer_tests=4,general_summer_interval=False,other_year_release=False,expansion=False,external_sending=False)
 tag='current2023_effect_release_20261006';s+='\n'+yaml.safe_dump({tag:section},sort_keys=False);p.write_text(s)
 current=yaml.load(s,Loader=UniqueLoader);normal=copy.deepcopy(current);normal.pop(tag)
 for k in ['updated_on','status','next_actions_not_executed']:normal[k]=old[k]
 for k in ['current_user_request','current_pre_update_snapshot']:normal['authority'][k]=old['authority'][k]
 normal['control_boundary']['coefficient_unsealing_authorized_by_this_update']=old['control_boundary']['coefficient_unsealing_authorized_by_this_update']
 normal['stage_1']['point_estimates']=old['stage_1']['point_estimates'];normal['scale_decision']['tolerance_status']=old['scale_decision']['tolerance_status']
 normal['pilot_precision_and_release']['current_release_sequence']=old['pilot_precision_and_release']['current_release_sequence']
 if normal!=old:raise ValueError('Unplanned scientific protocol change')
 decision=dict(status='CURRENT2023_EXPLORATORY_RESULTS_RELEASED_AND_REVIEWED',effect_review_complete=True,
  previous_display_hold_superseded=True,scale_tolerance=None,formal_scale_agreement=None,later_margin_requires_prior_access_disclosure=True,
  baseline_retained=True,primary_outcome='temperature',general_summer_interval=False,
  finding='negative selected-date Phoenix contrast persists in original/common/quadratic checks; magnitude sensitive to population/model/alignment',
  next_priorities=next_steps,expansion_authorized=False,external_sending=False,report=section['report'])
 write(EXEC/'decision_record.json',decision);write(PACKET/'decision_record.json',decision)
 write(EXEC/'documentation_verification.json',dict(status='PASS',unique_yaml_keys=True,unrelated_scientific_rules_preserved=True,
  current_sealing_hold_removed=True,formal_tolerance_ruling_separate=True,historical_records_preserved=True,
  archived_effect_figures_visually_reviewed=39,new_review_figures_visually_reviewed=6,active_documents_archived=6))
 write(EXEC/'review_completion.json',dict(status='COMPLETE',new_effects_released=True,scope_sha256=sha(EXEC/'scope.json'),
  followup_scope_sha256=sha(EXEC/'post_disclosure_joint_freeze.json'),scientific_review=decision,
  source_artifacts='Original filenames/permissions retained for provenance; current2023 review access is authorized',
  no_external_message=True))

if __name__=='__main__':main()
