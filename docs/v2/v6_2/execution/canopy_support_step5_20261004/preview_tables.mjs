import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook} from '@oai/artifact-tool';
const here=path.dirname(new URL(import.meta.url).pathname);const root=path.resolve(here,'../../../../../');
const matrices=JSON.parse(await fs.readFile(path.join(root,'outputs/v6_2/scientific/canopy_support_step5_20261004/public_table_matrices.json'),'utf8'));
const specs=[
 {file:'endpoint_support.csv',title:'Historical support',cols:['city','date','spanning_blocks','reference_cell_fraction','lower_fraction','upper_fraction'],heads:['City','Date','Spanning blocks','Reference frac','Lower band frac','Upper band frac'],filter:r=>r.pair_id==='historical'&&r.halfwidth_fraction===.01},
 {file:'endpoint_covariate_profiles.csv',title:'Covariate profiles',cols:['city','endpoint','variable','n','median','p95'],heads:['City','Endpoint','Variable','Cells','Median','P95'],filter:r=>r.orbit==='27835'&&r.halfwidth_fraction===.01},
 {file:'design_diagnostics.csv',title:'Quadratic designs',cols:['city','date','rank','n_parameters','scaled_design_condition','removed_context_terms'],heads:['City','Date','Rank','Columns','Scaled condition','Removed controls'],filter:r=>r.model==='quadratic'},
 {file:'design_resampling.csv',title:'Design resampling',cols:['city','date','group_km','linear_estimable','quadratic_estimable','paired_failed'],heads:['City','Date','Group km','Linear valid','Quadratic valid','Paired failed'],filter:r=>r.group_km===8},
 {file:'cross_city_context_distances.csv',title:'Joint context distances',cols:['city','date','query_cells','median','p05','p95'],heads:['Query city','Date','Query cells','Median distance','P5 distance','P95 distance'],filter:r=>r.endpoint==='lower'&&r.halfwidth_fraction===.025},
 {file:'cross_city_reference_profiles.csv',title:'Reference profiles',cols:['city','variable','n','p05','median','p95'],heads:['City','Variable','Cells','P5','Median','P95'],filter:r=>r.endpoint==='lower'&&r.halfwidth_fraction===.025},
];
for(const spec of specs){
 const input=matrices[spec.file];const records=input.rows.map(row=>Object.fromEntries(input.headers.map((k,i)=>[k,row[i]]))).filter(spec.filter);
 const matrix=[spec.heads,...records.map(r=>spec.cols.map(c=>r[c]))];
 const wb=Workbook.create();const sheet=wb.worksheets.add(spec.title);const range=sheet.getRangeByIndexes(0,0,matrix.length,spec.cols.length);range.values=matrix;
 range.format.font={name:'Arial',size:11};range.format.rowHeightPx=28;range.format.columnWidthPx=150;
 for(const [i,c]of spec.cols.entries()){
  if(c==='variable')sheet.getRangeByIndexes(0,i,matrix.length,1).format.columnWidthPx=270;
  if(['median','p05','p95','scaled_design_condition','reference_cell_fraction','lower_fraction','upper_fraction'].includes(c))sheet.getRangeByIndexes(1,i,matrix.length-1,1).setNumberFormat('0.0000');
 }
 sheet.getRangeByIndexes(0,0,1,spec.cols.length).format.fill='#E7EDF4';sheet.getRangeByIndexes(0,0,1,spec.cols.length).format.font={name:'Arial',size:11,bold:true,color:'#20334D'};
 await wb.recalculate();const preview=await wb.render({sheetName:spec.title,autoCrop:'all',scale:1.5,format:'png'});
 await fs.writeFile(path.join(here,'qa',spec.file.replace('.csv','_preview.png')),new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({predictorTablePreviews:6,outcomeAccess:false}));
