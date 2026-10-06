// Read-only QA views of the four public CSVs. No effect data or output mutation.
import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook} from '@oai/artifact-tool';
const execDir=path.dirname(new URL(import.meta.url).pathname);
const root=path.resolve(execDir,'../../../../../');
const out=path.join(root,'deliverables/Spatial_Scale_Review_2023_v6_2_20261004');
const qa=path.join(execDir,'qa');
await fs.mkdir(qa,{recursive:true});
const specs=[
  {file:'spatial_precision_review.csv',name:'Joint precision',headers:['Date','Orbit','Group km','T SE K/10pp','T width95','Valid draws','Failed draws'],columns:['date','orbit','group_km','T_SE_K_per_10pp','T_width95_K_per_10pp','bootstrap_estimable','bootstrap_failed'],filter:r=>r.kind==='joint_common_minus_original',widths:[125,90,95,130,130,105,105]},
  {file:'canopy_context_distributions.csv',name:'Predictor distributions',headers:['Variable','Population','Cells','Median','P99','Max'],columns:['variable','population','n','q50','q99','q100'],filter:r=>r.orbit==='27963',widths:[260,230,100,120,120,125]},
  {file:'footprint_and_reference_support.csv',name:'Footprint and reference',headers:['City','Date','Original cells','Common cells','Retained frac','Ref blocks'],columns:['city','date','original_cells','common_all11_cells','common_all11_retained_fraction','reference_supporting_blocks'],filter:r=>true,widths:[100,130,130,130,130,120]},
  {file:'inherited_residual_spatial_diagnostics.csv',name:'Inherited residuals',headers:['City','Orbit','Boundary km','Neighbor pairs','T corr','M corr'],columns:['city','orbit','boundary_km','cross_boundary_neighbor_pairs','LST_K_residual_cross_boundary_correlation','M_W_m2_residual_cross_boundary_correlation'],filter:r=>true,widths:[100,100,125,135,130,130]},
];
for(const spec of specs){
 const imported=await Workbook.fromCSV(await fs.readFile(path.join(out,spec.file),'utf8'),{sheetName:'Source'});
 const source=imported.worksheets.getItem('Source');
 const dictionaries=JSON.parse(await fs.readFile(path.join(out,'data_dictionary.json'),'utf8')).tables[spec.file];
 const counts=JSON.parse(await fs.readFile(path.join(execDir,'csv_author_verification.json'),'utf8')).tables.find(x=>x.file===spec.file);
 const cells=source.getRangeByIndexes(0,0,counts.rows+1,dictionaries.length).values;
 const records=cells.slice(1).map(row=>Object.fromEntries(cells[0].map((name,i)=>[name,row[i]===null?'':String(row[i])]))).filter(spec.filter);
 const matrix=[spec.headers,...records.map(r=>spec.columns.map(c=>r[c]===''?null:(!['city','date','orbit','variable','population'].includes(c)?Number(r[c]):r[c])))];
 const wb=Workbook.create();const sheet=wb.worksheets.add(spec.name);
 sheet.getRangeByIndexes(0,0,matrix.length,spec.columns.length).values=matrix;
 const range=sheet.getRangeByIndexes(0,0,matrix.length,spec.columns.length);
 range.format.font={name:'Arial',size:11};range.format.rowHeightPx=27;
 for(const [i,w]of spec.widths.entries())sheet.getRangeByIndexes(0,i,matrix.length,1).format.columnWidthPx=w;
 sheet.getRangeByIndexes(0,0,1,spec.columns.length).format.fill='#E7EDF4';
 sheet.getRangeByIndexes(0,0,1,spec.columns.length).format.font={name:'Arial',size:11,bold:true,color:'#20334D'};
 for(const [i,c]of spec.columns.entries())if(['T_SE_K_per_10pp','T_width95_K_per_10pp','q50','q99','q100','common_all11_retained_fraction','LST_K_residual_cross_boundary_correlation','M_W_m2_residual_cross_boundary_correlation'].includes(c))sheet.getRangeByIndexes(1,i,matrix.length-1,1).setNumberFormat('0.0000');
 await wb.recalculate();
 const image=await wb.render({sheetName:spec.name,autoCrop:'all',scale:1.5,format:'png'});
 await fs.writeFile(path.join(qa,spec.file.replace('.csv','_preview.png')),new Uint8Array(await image.arrayBuffer()));
}
console.log(JSON.stringify({publicCSVPreviews:4,effectDataRead:false}));
