"""Record Step7 computation/calibration and preserve earlier protocol history."""
import copy
import json
from pathlib import Path
import sys
import yaml
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
from v6_2_advance.run_step7_window import EXEC,PACKET,ACTIVE,public,synthetic,sha,write
ARCHIVE=ROOT/'docs/v2/v6_2/archive/before_step7_window_20261005'

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
 verified=json.loads((EXEC/'verification.json').read_text())
 if verified['status']!='PASS':raise ValueError('Verification incomplete')
 for rel in ACTIVE:
  if sha(ROOT/rel)!=sha(ARCHIVE/rel):raise ValueError('Active file changed since snapshot')
 statement=("The 5 October 2026 ‘do the next steps’ and ‘keep going’ continuation authorized Step7 internal fixed-date Phoenix window calculations and actual-design synthetic uncertainty assessment. "
  "Completion is recorded in `docs/v2/v6_2/execution/step7_window_20261005/` and `deliverables/Step7_Window_2023_v6_2_20261005/`. "
  "The earlier hold is superseded only for this bounded computation and its explicitly hypothetical calibration grid. All sixteen original linear temperature estimates were recovered; "
  "all32,000 city-specific joint physical-group pass draws were estimable. Combined/monthly Phoenix effects, two supported date deletions and their influence changes are sealed; "
  "three other deletions remain unsupported. Flux is averaged within each arm before reference inversion and arm differencing. "
  "The synthetic production assessment used216 scenarios and432,000 datasets, with no empirical effect means as inputs; it does not establish a general summer interval. "
  "The existing day bootstrap and variance-separation candidate undercovered in some frozen scenarios, and no broader empirical interval or new time model was adopted. "
  "Atlanta had a synthetic-only design check, not a new empirical contrast. Methods/captions and a targeted-observation proposal are prepared. "
  "New empirical effects and figures remain sealed/unviewed, Reza's tolerance and scale ruling remain pending, and no new city/year processing or acquisition is authorized by the proposal.")
 p=ROOT/'AGENTS.md';p.write_text(p.read_text().replace('## Scope and preservation',statement+'\n\n## Scope and preservation',1))
 p=ROOT/'docs/v2/v6_2/pilot_plan_v6_2.md';text=p.read_text();i=text.index('\n');p.write_text(text[:i+1]+'\n## Current Step 7 status — 5 October 2026\n\n'+statement+'\n'+text[i+1:])
 p=ROOT/'docs/v2/v6_2/results_review_and_targeted_analysis_plan_20260930.md';text=p.read_text();i=text.index('\n')
 text=text[:i+1]+'\n**Latest status: Step7 internal computation and synthetic calibration are complete; no general summer interval is adopted.** '+statement+'\n'+text[i+1:]
 marker='### Step 7 Calibrate uncertainty before reporting a general time interval'
 text=text.replace(marker,marker+'\n\n**Completed internally on 5 October 2026.** Fixed-date comparisons are sealed; the public calibration and decision record explain why no broader summer interval was adopted. The frozen original linear model, sample and comparison weights remain unchanged.',1);p.write_text(text)
 p=ROOT/'docs/v2/v6_2/decision_log_v6_2.md';p.write_text(p.read_text()+'\n\n### 5 October 2026 — Step 7 fixed-date uncertainty and synthetic calibration\n\n'+statement+'\n\n'
  'Freeze the original samples, shared physical-group resampling, exact arm-average flux transformation, supported deletion weights and all simulation settings before empirical comparison computation. '
  'The 1km/8km union-group draws account for recurring geography and structurally absent groups. No old empirical time-effect file was opened and no control, group or draw was replaced. '
  'All56 public comparison rows contain only precision and draw accounting; empirical points and confidence endpoints remain in private files. The two effect figures were machine-checked but not visually reviewed.\n\n'
  'Synthetic amplitudes −0.30/0/+0.30 K per10pp and day SDs0/0.05/0.15 are declared assumptions, not empirical effect calibration or Reza tolerance. '
  'The actual schedules, dates and joint8km spatial covariance define216 scenarios with six mean/day profiles and two correlation settings. '
  'Methods were unchanged between21,600 development datasets and432,000 independent production datasets. Simulation covariance is a fixed plug-in input; Gaussian pass errors and synthetic day processes are assumptions. '
  'The candidate common-day-variance moment estimator is not REML/Hartung-Knapp, is not fitted empirically, and does not establish general-season uncertainty. '
  'Coverage ranges and Monte Carlo error are reported without a retrospective acceptance gate. Independent-date bootstrap support loss and two rank-deficient Atlanta bank draws are retained in the audit.\n\n'
  'Thirteen network-free known-answer/boundary checks,22 input hashes,11 source hashes, original-point recovery, paired covariance/interval reconstruction and sealed-output checks passed. '
  'Public precision and synthetic figures were visually checked, with layout-only refinements separately recorded. The initial explicit-bootstrap test fixture was corrected to map draws by coarse physical group rather than lexicographic fine-block label; no scientific algorithm was changed after freezing. '
  'The next-observation document specifies design priorities only; no new screening, acquisition, year/city expansion, external communication, commit or push occurred.\n')
 p=ROOT/'docs/v2/v6_2/prior_thermal_access.md';p.write_text(p.read_text()+'\n\n### 5 October 2026 — internal Step7 comparison and synthetic calibration\n\n'
  'Under the latest continuation, code decoded the sixteen original cached paired native-cell frames, reconstructed the frozen linear models, '
  'verified them against the previously released temperature table, and generated joint physical-group draws across dates. '
  'New Phoenix window/monthly/deletion/influence effects and paired flux equivalents were calculated and stored under `outputs/v6_2/sealed_coefficients/step7_window_20261005/`. '
  'Verification read these new files programmatically; no pre-existing empirical time-effect file or new satellite thermal raster was opened. '
  'No new effect point, sign, confidence endpoint or significance result was displayed or visually inspected. '
  'The public spatial covariance is a precision output. Calibration reads that covariance and nonthermal schedules, but no empirical effect means; its outcomes are explicitly synthetic. '
  'Only public precision and synthetic figures were viewed. The release boundary and prior thermal-access history remain unchanged; global outcome blindness is not claimed.\n')
 p=ROOT/'docs/v2/v6_2/protocol_v6_2.yml';old=yaml.load(p.read_text(),Loader=UniqueLoader);text=p.read_text()
 edits={
  'status: '+old['status']:'status: STEP7_INTERNAL_WINDOW_AND_CALIBRATION_COMPLETE_EFFECTS_SEALED_2023',
  '  current_user_request: '+old['authority']['current_user_request']:'  current_user_request: 2026-10-05_next_steps_and_keep_going_Step7_internal_window_and_synthetic_calibration_complete',
  '  current_pre_update_snapshot: '+old['authority']['current_pre_update_snapshot']:'  current_pre_update_snapshot: docs/v2/v6_2/archive/before_step7_window_20261005',
  '  Step6_nonthermal_inputs_executed: true':'  Step6_nonthermal_inputs_executed: true\n  Step7_internal_window_and_calibration_executed: true',
  '- calibrate_proposed_Phoenix_window_uncertainty_after_completed_Step6_conditions':'- review_completed_fixed_date_and_synthetic_calibration_without_general_summer_promotion',
  '  uncertainty: carry_stage1_uncertainty_and_resample_independent_pass_or_day_clusters_not_native_pixels':'  uncertainty: fixed_date_joint_physical_groups; general_day_interval_not_adopted; no_extra_independent_Stage1_jitter_on_observed_day_estimates; see_step7_window_20261005',
 }
 for a,b in edits.items():
  if text.count(a)!=1:raise ValueError('Protocol anchor changed')
  text=text.replace(a,b)
 tag='step7_window_calibration_20261005'
 section=dict(authority='User requests next steps and keep going; bounded internal window and synthetic assessment',
  status='COMPUTATION_COMPLETE_EFFECT_REVIEW_SEALED_NO_GENERAL_SUMMER_INTERVAL',
  execution_freeze='docs/v2/v6_2/execution/step7_window_20261005/execution_freeze.json',
  packet='deliverables/Step7_Window_2023_v6_2_20261005/README.md',year=2023,Phoenix_passes=11,Atlanta_passes=5,
  original_linear_points_recovered=16,mean_model_replaced=False,controls_retained=6,groups_km=[1,8],joint_pass_draws_requested=32000,joint_pass_draws_estimable=32000,
  physical_union_shared_across_dates=True,missing_group_zero_contribution=True,
  fixed_date_Phoenix_comparisons=['combined','June','August','drop_Aug06','drop_Aug23','influence_Aug06','influence_Aug23'],
  unsupported_deletions=[27963,28192,28909],public_precision_rows=56,
  flux_order='average within arm; exact fixed reference inversion; afternoon-minus-morning',
  empirical_Atlanta_contrast=False,development_datasets=21600,production_scenarios=216,production_datasets_per_scenario=2000,production_datasets=432000,
  synthetic_amplitudes=[-.3,0,.3],synthetic_day_SDs=[0,.05,.15],synthetic_parameters_empirically_calibrated=False,
  synthetic_covariance='actual8km spatial precision treated as fixed/known; diagonal/full sensitivities',
  methods_tuned_to_empirical_effect=False,new_empirical_general_day_variance_model=False,general_summer_interval=False,
  new_effect_display=False,empirical_effect_visual_review=False,scale_tolerance=None,scale_ruling=None,
  proposed_next_observations_only=True,new_screening_or_acquisition=False,known_answer_tests=13,frozen_input_hashes=22,frozen_code_hashes=11)
 text+='\n'+yaml.safe_dump({tag:section},sort_keys=False);p.write_text(text)
 current=yaml.load(text,Loader=UniqueLoader);normal=copy.deepcopy(current);normal.pop(tag)
 for k in ('status','next_actions_not_executed'):normal[k]=old[k]
 for k in ('current_user_request','current_pre_update_snapshot'):normal['authority'][k]=old['authority'][k]
 normal['control_boundary'].pop('Step7_internal_window_and_calibration_executed');normal['time_analysis']['uncertainty']=old['time_analysis']['uncertainty']
 if normal!=old:raise ValueError('Unplanned protocol change')
 decision=dict(status=section['status'],authorized_computations_complete=True,effect_review_complete=False,
  retain='original linear models,16pass2023 baseline, frozen Phoenix weights',new_effect_display=False,
  general_summer_interval_adopted=False,reason='sparse independent dates, observed condition differences and undercoverage/support loss in frozen synthetic stress scenarios',
  automatic_method_promotion=False,empirical_Atlanta_contrast=False,scale_ruling=None,expansion=False,
  next_proposal='deliverables/Step7_Window_2023_v6_2_20261005/next_observation_proposal.md')
 write(EXEC/'decision_record.json',decision);write(PACKET/'decision_record.json',decision)
 write(EXEC/'documentation_verification.json',dict(status='PASS',unique_yaml_keys=True,unrelated_protocol_fields_preserved=True,
  active_files_archived=6,public_figures_visually_checked=2,sealed_effect_figures_visually_checked=False,source_hashes_preserved=True))

if __name__=='__main__':main()
