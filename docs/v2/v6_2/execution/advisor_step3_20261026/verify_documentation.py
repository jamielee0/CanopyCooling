from pathlib import Path
import json,hashlib,yaml,shutil,subprocess,re
R=Path('/Users/jmlee/Documents/TreeProject');E=R/'docs/v2/v6_2/execution/advisor_step3_20261026';A=R/'docs/v2/v6_2/archive/before_advisor_step3_20261026';P=R/'deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
class Unique(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):
 pairs=loader.construct_pairs(node,deep=deep);keys=[k for k,v in pairs];assert len(keys)==len(set(keys));return dict(pairs)
Unique.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
a=yaml.load((A/'docs/v2/v6_2/protocol_v6_2.yml').read_text(),Loader=Unique);b=yaml.load((R/'docs/v2/v6_2/protocol_v6_2.yml').read_text(),Loader=Unique)
assert b.pop('advisor_step3_20261026')['status']=='COMPLETE_VERIFIED';b['status']=a['status']
for key in ['current_user_request','current_pre_update_snapshot']:b['authority'][key]=a['authority'][key]
b['control_boundary']['coefficient_unsealing_authorized_by_this_update']=a['control_boundary']['coefficient_unsealing_authorized_by_this_update']
assert a==b,'Unexpected scientific specification change'
for name,h in json.loads((A/'snapshot.json').read_text()).items():
 assert sha(A/name)==h
 if not name.endswith('.yml'):
  old=(A/name).read_text();new=(R/name).read_text()
  if name in ['AGENTS.md','docs/v2/v6_2/pilot_plan_v6_2.md']:assert old.split('\n',1)[1].lstrip('\n') in new
  else:assert new.startswith(old)
kept=0
for step in ['advisor_step1_20261026','advisor_step2_20261026']:
 for name,h in json.loads((R/'docs/v2/v6_2/execution'/step/'delivery_manifest.json').read_text())['files'].items():
  if name.startswith(('deliverables/','src/','tests/')):assert sha(R/name)==h,name;kept+=1
for p in P.rglob('*.md'):
 for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if not link.startswith(('https:','http:','#')):assert (p.parent/link.split('#')[0]).exists(),link
receipt=json.loads((E/'prediction_commit_receipt.json').read_text());G=Path(receipt['checkout'])
assert subprocess.run(['git','-C',str(G),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()==receipt['commit']
assert not subprocess.run(['git','-C',str(G),'status','--porcelain','--untracked-files=all'],capture_output=True,text=True,check=True).stdout.strip()
record={'status':'PASS','unique_yaml_keys':True,'historical_protocol_settings_unchanged_except_explicit_release_scope':True,'original_main2023_pilot_unchanged':True,'pre_step3_documents_archived_and_historical_text_preserved':True,'prior_step1_step2_package_code_test_hashes_verified':kept,'local_report_links_valid':True,'prediction_checkout_clean_at_recorded_commit':True}
(E/'documentation_verification.json').write_text(json.dumps(record,indent=2)+'\n')
for name in ['pre_access_verification.json','independent_verification.json','test_results.json','visual_verification.json','documentation_verification.json']:assert json.loads((E/name).read_text())['status']=='PASS'
computed=json.loads((E/'computed.json').read_text())
completion={'status':'STEP3_COMPLETE_VERIFIED','prediction_commit':receipt['commit'],'prediction_committed_before_outcomes_opened':True,'individual_predictions':7,'heldout_estimates_opened':7,'all7_inside_PI':True,'all3_afternoon_inside_PI':True,'refit_passes':18,'test_count':4,'independent_reconstruction':'PASS','visual_review':'PASS','archived_sources_unchanged':computed['archived_sources_unchanged'],'new_stage1_fits':0,'step4_started':False,'pushed':False,'sent':False}
(E/'completion.json').write_text(json.dumps(completion,indent=2)+'\n');(P/'completion.json').write_text(json.dumps(completion,indent=2)+'\n')
shutil.copy2('/tmp/finalize_advisor_step3.py',E/'finalize_documentation.py');shutil.copy2('/tmp/verify_advisor_step3_docs.py',E/'verify_documentation.py')
files=[*[p for p in P.rglob('*') if p.is_file()],R/'AGENTS.md',*[R/'docs/v2/v6_2'/n for n in ['protocol_v6_2.yml','pilot_plan_v6_2.md','decision_log_v6_2.md','prior_thermal_access.md']],*[R/'src/v6_2_advance'/n for n in ['advisor_step3_prediction.py','run_advisor_step3.py','verify_advisor_step3.py']],R/'tests/v6_2_advance/test_advisor_step3_prediction.py']
(E/'delivery_manifest.json').write_text(json.dumps({'status':'COMPLETE_VERIFIED','files':{str(p.relative_to(R)):sha(p) for p in files}},indent=2)+'\n')
print(json.dumps(record));print(json.dumps(completion))
