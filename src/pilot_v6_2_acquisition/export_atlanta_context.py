"""Stage nonthermal Atlanta inputs only. Reuse identical descriptions on retries."""
from pathlib import Path
import ee,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from run_v6_2_tcc_export_to_drive import SOURCE_CRS_WKT,SOURCE_TRANSFORM
out=(ROOT/'docs/v2/v6_2/execution');ee.Initialize(project='tree-497018')
g=[f['geometry'] for f in json.loads((out/'candidate_domains.geojson').read_text())['features'] if f['properties']['city']=='atlanta'][0]
region=ee.Geometry(g,geodesic=False);folder='Urban_Tree_Cooling_v6_2_pilot_20260919';existing={t['description']:t for t in ee.data.getTaskList() if 'description' in t};records=[]
def export(image,name,crs,transform):
 if name in existing and existing[name]['state'] in ['READY','RUNNING','COMPLETED']:
  records.append({'name':name,'task_id':existing[name]['id'],'state':existing[name]['state']});return
 task=ee.batch.Export.image.toDrive(image=image.clip(region),description=name,folder=folder,fileNamePrefix=name,region=region,crs=crs,crsTransform=transform,maxPixels=1e9,fileFormat='GeoTIFF',formatOptions={'cloudOptimized':True,'noData':-9999})
 task.start();records.append({'name':name,'task_id':task.id,'state':task.status()['state']})
for y in range(2019,2026):
 image=ee.Image(f'projects/gtac-data-publish/assets/TCC/Product_Version/2025-6/TCC_v2025-6_CONUS_{y}').select(['Science_Percent_Tree_Canopy_Cover','Science_Percent_Tree_Canopy_Cover_Standard_Error']).toInt16()
 export(image,f'science_tcc_v2025-6_atlanta_{y}_native30m',SOURCE_CRS_WKT,SOURCE_TRANSFORM)
# Match inherited Phoenix 2021 impervious and validity companion exactly.
image=ee.Image('USGS/NLCD_RELEASES/2021_REL/NLCD/2021').select(['impervious','landcover']).toInt16();proj=image.select('impervious').projection().getInfo()
export(image,'atlanta_nlcd_2021_impervious_and_validity',proj.get('crs',proj.get('wkt')),proj['transform'])
dem=ee.Image('USGS/3DEP/10m').select('elevation').toFloat();proj=dem.projection().getInfo();export(dem,'usgs_3dep_10m_atlanta_frozen_census_domain',proj.get('crs',proj.get('wkt')),proj['transform'])
(out/'atlanta_context_export_manifest.json').write_text(json.dumps({'folder':folder,'exports':records,'thermal_data':False},indent=2));print(json.dumps(records))
