import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {Workbook} from '@oai/artifact-tool';
const here=path.dirname(new URL(import.meta.url).pathname);
const root=path.resolve(here,'../../../../../');
const source=path.join(root,'outputs/v6_2/scientific/canopy_support_step5_20261004');
const out=path.join(root,'deliverables/Step5_Canopy_Support_2023_v6_2_20261004');
const tables=JSON.parse(await fs.readFile(path.join(source,'public_table_matrices.json'),'utf8'));
const report=[];
for(const [filename,input] of Object.entries(tables)){
 const wb=Workbook.create();const sheet=wb.worksheets.add('Data');
 const matrix=[input.headers,...input.rows];
 const encoded=matrix.map((row,i)=>i?row.map(v=>typeof v==='string'?`'${v}`:v):row);
 const range=sheet.getRangeByIndexes(0,0,matrix.length,input.headers.length);
 range.values=encoded;await wb.recalculate();
 const actual=range.values;
 if(JSON.stringify(actual)!==JSON.stringify(encoded))throw new Error('Typed predictor-only table changed');
 const decoded=actual.map((row,i)=>i?row.map(v=>typeof v==='string'?v.slice(1):v):row);
 if(JSON.stringify(decoded)!==JSON.stringify(matrix))throw new Error('Literal-text roundtrip changed');
 const cell=v=>{if(v===null)return '';const s=String(v);return /[",\r\n]/.test(s)?`"${s.replaceAll('"','""')}"`:s;};
 const csv=decoded.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';
 await fs.writeFile(path.join(source,filename),csv);await fs.writeFile(path.join(out,filename),csv);
 report.push({file:filename,rows:input.rows.length,columns:input.headers.length,sha256:crypto.createHash('sha256').update(csv).digest('hex'),typedRoundtrip:true});
}
await fs.writeFile(path.join(here,'csv_verification.json'),JSON.stringify({author:'@oai/artifact-tool',tables:report,outcomeValues:false},null,2)+'\n');
console.log(JSON.stringify({tables:report.map(({file,rows,columns})=>({file,rows,columns})),outcomeValues:false}));
