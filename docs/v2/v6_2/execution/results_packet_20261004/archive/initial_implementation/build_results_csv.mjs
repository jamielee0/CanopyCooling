// Author the flat scientific CSV in artifact-tool, preserving typed frozen data.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { Workbook } from '@oai/artifact-tool';

const execDir = path.dirname(new URL(import.meta.url).pathname);
const root = path.resolve(execDir, '../../../../../');
const out = path.join(root, 'deliverables/Results_Review_2023_v6_2_20261004');
const input = JSON.parse(await fs.readFile(path.join(execDir, 'results_matrix.json'), 'utf8'));
const header = input.fields.map(f => f.name);
const matrix = [header, ...input.rows];
const wb = Workbook.create();
const sheet = wb.worksheets.add('Results');
const range = sheet.getRangeByIndexes(0, 0, matrix.length, header.length);
range.values = matrix;
await wb.recalculate();
const retrieved = range.values;
if (JSON.stringify(retrieved) !== JSON.stringify(matrix)) throw new Error('Artifact sheet changed a typed value');
const inspection = await wb.inspect({kind: 'region', sheetId: sheet.id, range: 'A1:N5', maxChars: 2800, tableMaxRows: 5, tableMaxCols: 14});
await fs.writeFile(path.join(execDir, 'artifact_inspection.txt'), inspection.ndjson);

// Public API documents XLSX export only; serialize verified sheet values to the
// requested CSV format. RFC4180 quoting, full JS double precision, null=blank.
const csvCell = value => {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const csv = retrieved.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
const csvPath = path.join(out, 'pass_results_long.csv');
await fs.writeFile(csvPath, csv, 'utf8');

// Compact QA view of original point results and both plotted intervals. This is
// a preview only; the analytical CSV retains every field and all 64 records.
const index = Object.fromEntries(header.map((name, i) => [name, i]));
const originals = input.rows.filter(r => r[index.variant] === 'original');
const previews = [['City', 'Date', 'Solar hour', 'Cooling K/10pp', 'SE 1km', 'SE 8km', 'Lower 8km', 'Upper 8km']];
for (const r of originals) {
  const r8 = input.rows.find(s => s[index.city] === r[index.city] && s[index.orbit] === r[index.orbit] && s[index.source_run_id] === r[index.source_run_id] && s[index.resampling_group_km] === 8);
  previews.push([r[index.city], r[index.local_date], r[index.apparent_solar_hour], r[index.cooling_K_per_10pp], r[index.spatial_SE_K_per_10pp], r8[index.spatial_SE_K_per_10pp], r8[index.cooling_q025_K_per_10pp], r8[index.cooling_q975_K_per_10pp]]);
}
const previewSheet = wb.worksheets.add('Review preview');
previewSheet.getRangeByIndexes(0, 0, previews.length, 8).values = previews;
previewSheet.getRange('A1:H17').format.font = {name: 'Arial', size: 11};
previewSheet.getRange('A1:H17').format.columnWidthPx = 135;
previewSheet.getRange('B1:B17').format.columnWidthPx = 145;
previewSheet.getRange('D1:D17').format.columnWidthPx = 175;
previewSheet.getRange('A1:H17').format.rowHeightPx = 28;
previewSheet.getRange('A1:H1').format.fill = '#E7EDF4';
previewSheet.getRange('A1:H1').format.font = {name: 'Arial', size: 11, bold: true, color: '#20334D'};
previewSheet.getRange('C2:H17').setNumberFormat('0.000');
await wb.recalculate();
const preview = await wb.render({sheetName: 'Review preview', range: 'A1:H17', scale: 1.5, format: 'png'});
await fs.writeFile(path.join(execDir, 'qa', 'table_preview.png'), new Uint8Array(await preview.arrayBuffer()));
await fs.writeFile(path.join(execDir, 'csv_author_verification.json'), JSON.stringify({
  author: '@oai/artifact-tool', format: 'RFC4180 CSV from exact verified typed sheet values',
  rows: input.rows.length, columns: header.length, exact_value_roundtrip: true,
  csv_sha256: crypto.createHash('sha256').update(csv).digest('hex'),
  missing_encoding: 'empty field, never zero', preview: 'qa/table_preview.png',
}, null, 2) + '\n');
console.log(JSON.stringify({csv: csvPath, rows: input.rows.length, columns: header.length, exactValueRoundtrip: true}));
