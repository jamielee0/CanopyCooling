from pathlib import Path
import ee,json,hashlib,os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
ROOT=Path(__file__).resolve().parents[2];stage=(ROOT/'docs/v2/v6_2/execution');out=ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_context'
ee.Initialize(project='tree-497018');manifest=json.loads((stage/'atlanta_context_export_manifest.json').read_text());statuses=ee.data.getTaskStatus([r['task_id'] for r in manifest['exports']]);print('EXPORT_STATUS',json.dumps([{k:r.get(k) for k in ['id','state','error_message']} for r in statuses]),flush=True)
service=build('drive','v3',credentials=ee.data.get_persistent_credentials(),cache_discovery=False)
folders=service.files().list(q="name='Urban_Tree_Cooling_v6_2_pilot_20260919' and mimeType='application/vnd.google-apps.folder' and trashed=false",fields='files(id,name)').execute()['files'];records=[]
for folder in folders:
 token=None
 while True:
  res=service.files().list(q=f"'{folder['id']}' in parents and trashed=false",fields='nextPageToken,files(id,name,size,md5Checksum)',pageSize=1000,pageToken=token).execute()
  for item in res['files']:
   if not item['name'].endswith('.tif'):continue
   p=out/item['name'];size=int(item['size'])
   if not p.exists() or p.stat().st_size!=size:
    tmp=p.with_suffix('.partial')
    with tmp.open('wb') as f:
     dl=MediaIoBaseDownload(f,service.files().get_media(fileId=item['id']),chunksize=8*1024*1024);done=False
     while not done:_,done=dl.next_chunk()
    if tmp.stat().st_size!=size:raise ValueError('Download size mismatch')
    tmp.replace(p)
   md5=hashlib.md5(p.read_bytes()).hexdigest()
   if md5!=item['md5Checksum']:raise ValueError('MD5 mismatch')
   records.append({**item,'local_path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'verified_md5':True})
  token=res.get('nextPageToken')
  if not token:break
(out/'earth_engine_download_manifest.json').write_text(json.dumps({'task_status':statuses,'files':records},indent=2));print('VERIFIED_EXPORTED_FILES',len(records))
