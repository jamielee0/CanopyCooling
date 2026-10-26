from pathlib import Path
import hashlib,json,yaml
R=Path('/Users/jmlee/Documents/TreeProject'); E=R/'docs/v2/v6_2/execution/advisor_step1_20261026'; A=R/'docs/v2/v6_2/archive/before_advisor_step1_20261026'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
class UniqueLoader(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):
 pairs=loader.construct_pairs(node,deep=deep);keys=[k for k,v in pairs]
 assert len(keys)==len(set(keys)),keys
 return dict(pairs)
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
old=yaml.load((A/'docs/v2/v6_2/protocol_v6_2.yml').read_text(),Loader=UniqueLoader)
new=yaml.load((R/'docs/v2/v6_2/protocol_v6_2.yml').read_text(),Loader=UniqueLoader)
assert new.pop('advisor_step1_20261026')['status']=='COMPLETE_INPUTS_ONLY'
for key in ('updated_on','status'):new[key]=old[key]
for key in ('current_user_request','current_pre_update_snapshot'):new['authority'][key]=old['authority'][key]
assert new==old,'Unintended prior scientific configuration change'
files=json.loads((A/'snapshot.json').read_text())['files']
for x in files:assert sha(A/x['path'])==x['sha256'],x['path']
for name in ('AGENTS.md','docs/v2/v6_2/pilot_plan_v6_2.md','docs/v2/v6_2/decision_log_v6_2.md','docs/v2/v6_2/prior_thermal_access.md'):
 a=(A/name).read_text(); b=(R/name).read_text()
 assert ('advisor_step1_20261026' in b)
 if name in ('AGENTS.md','docs/v2/v6_2/pilot_plan_v6_2.md'):assert a.split('\n',1)[1].lstrip('\n') in b
 else:assert b.startswith(a)
report={'status':'PASS','duplicate_yaml_keys':False,'historical_scientific_configuration_unchanged':True,'pre_update_archived_files_verified':len(files),'earlier_document_text_preserved':True}
(E/'documentation_verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
