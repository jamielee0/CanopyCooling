// Scientific tables only; input schema carries no new effect points/endpoints.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {Workbook} from '@oai/artifact-tool';
const execDir = path.dirname(new URL(import.meta.url).pathname);
const root = path.resolve(execDir, '../../../../../');
const source = path.join(root, 'outputs/v6_2/scientific/spatial_scale_review_20261004');
const deliverable = path.join(root, 'deliverables/Spatial_Scale_Review_2023_v6_2_20261004');
const data = JSON.parse(await fs.readFile(path.join(source, 'public_table_matrices.json'), 'utf8'));
const wb = Workbook.create();
const encodeCell = v => typeof v === 'string' ? `'${v}` : v;
const csvCell = v => {if (v === null) return ''; const s = String(v); return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;};
const report = [];
for (const [filename, input] of Object.entries(data)) {
  const sheet = wb.worksheets.add(filename.replace('.csv','').slice(0,31));
  const matrix = [input.headers, ...input.rows];
  const encoded = matrix.map((row, r) => r ? row.map(encodeCell) : row);
  const range = sheet.getRangeByIndexes(0,0,matrix.length,input.headers.length);
  range.values = encoded;
  await wb.recalculate();
  const authored = range.values;
  if (JSON.stringify(authored)!==JSON.stringify(encoded)) throw new Error('Typed public data changed during sheet authoring');
  const decoded = authored.map((row,r) => r ? row.map(v => typeof v==='string' ? v.slice(1) : v) : row);
  if (JSON.stringify(decoded)!==JSON.stringify(matrix)) throw new Error('Literal-text decode failed');
  const csv = decoded.map(row => row.map(csvCell).join(',')).join('\r\n')+'\r\n';
  await fs.writeFile(path.join(source,filename),csv);
  await fs.writeFile(path.join(deliverable,filename),csv);
  report.push({file:filename,rows:input.rows.length,columns:input.headers.length,sha256:crypto.createHash('sha256').update(csv).digest('hex'),typedRoundtrip:true});
}
await fs.writeFile(path.join(execDir,'csv_author_verification.json'),JSON.stringify({author:'@oai/artifact-tool',literalTextPreserved:true,tables:report},null,2)+'\n');
console.log(JSON.stringify({tables:report.map(r=>({file:r.file,rows:r.rows,columns:r.columns})),effectPointsOrEndpointsExported:false}));
