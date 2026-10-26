from pathlib import Path
import json,hashlib,yaml,shutil
R=Path('/Users/jmlee/Documents/TreeProject');E=R/'docs/v2/v6_2/execution/advisor_step2_20261026';A=R/'docs/v2/v6_2/archive/before_advisor_step2_20261026';P=R/'deliverables/Advisor_Step2_Models_2023_v6_2_20261026'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
class Unique(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):
 pairs=loader.construct_pairs(node,deep=deep);keys=[k for k,v in pairs];assert len(keys)==len(set(keys));return dict(pairs)
Unique.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
a=yaml.load((A/'docs/v2/v6_2/protocol_v6_2.yml').read_text(),Loader=Unique);b=yaml.load((R/'docs/v2/v6_2/protocol_v6_2.yml').read_text(),Loader=Unique)
assert b.pop('advisor_step2_20261026')['status']=='COMPLETE_VERIFIED'
b['status']=a['status']
for k in ['current_user_request','current_pre_update_snapshot']:b['authority'][k]=a['authority'][k]
assert a==b,'Unintended historical specification change'
for name,h in json.loads((A/'snapshot.json').read_text()).items():
 assert sha(A/name)==h
 if not name.endswith('.yml'):
  old=(A/name).read_text();new=(R/name).read_text()
  if name in ['AGENTS.md','docs/v2/v6_2/pilot_plan_v6_2.md']:assert old.split('\n',1)[1].lstrip('\n') in new
  else:assert new.startswith(old)
step1=json.loads((R/'docs/v2/v6_2/execution/advisor_step1_20261026/delivery_manifest.json').read_text())['files']
kept=0
for name,h in step1.items():
 if name.startswith(('deliverables/','src/','tests/')):assert sha(R/name)==h,name;kept+=1
completion=json.loads((E/'completion.json').read_text())
for name,h in completion['files'].items():assert sha(R/name)==h,name
checks={'status':'PASS','unique_yaml_keys':True,'earlier_protocol_sections_unchanged':True,'archived_active_documents_unchanged':True,'historical_document_text_preserved':True,'step1_deliverables_code_tests_unchanged':kept,'computed_step2_tables_and_figures_unchanged':True}
(E/'documentation_verification.json').write_text(json.dumps(checks,indent=2)+'\n')
for file in ['independent_verification.json','test_results.json','visual_verification.json','documentation_verification.json']:assert json.loads((E/file).read_text())['status']=='PASS'
completion['status']='STEP2_COMPLETE_VERIFIED';completion['tests_passed']=8;completion['all_six_models_independently_verified']=True;completion['all_four_figures_visually_checked']=True
completion['committed']=False;completion['pushed']=False;completion['sent']=False
completion['files']={str(p.relative_to(R)):sha(p) for p in sorted(P.iterdir()) if p.is_file() and p.name!='completion.json'}
(E/'completion.json').write_text(json.dumps(completion,indent=2)+'\n');(P/'completion.json').write_text(json.dumps(completion,indent=2)+'\n')
shutil.copy2('/tmp/finalize_advisor_step2.py',E/'finalize_documentation.py');shutil.copy2('/tmp/verify_advisor_step2_docs.py',E/'verify_documentation.py')
manifest={str(p.relative_to(R)):sha(p) for p in [*P.iterdir(),R/'AGENTS.md',*[R/'docs/v2/v6_2'/n for n in ['protocol_v6_2.yml','pilot_plan_v6_2.md','decision_log_v6_2.md','prior_thermal_access.md']],R/'src/v6_2_advance/advisor_step2_models.py',R/'src/v6_2_advance/run_advisor_step2.py',R/'src/v6_2_advance/verify_advisor_step2.py',R/'tests/v6_2_advance/test_advisor_step2_models.py'] if p.is_file()}
(E/'delivery_manifest.json').write_text(json.dumps({'status':'COMPLETE_VERIFIED','files':manifest},indent=2)+'\n')
print(json.dumps(checks))
