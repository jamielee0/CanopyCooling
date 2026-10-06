import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { Workbook } = require("@oai/artifact-tool");

const HEADERS = [
  "record_role",
  "city",
  "year",
  "season_window",
  "sensor",
  "candidate_passes",
  "passes_with_feasible_matched_pre_post",
  "feasible_share",
  "unique_optical_acquisition_identifiers",
  "max_thermal_passes_sharing_one_acquisition",
  "minimum_shared_usable_blocks_in_selected_pairs",
  "median_shared_usable_blocks_in_selected_pairs",
  "timing_status",
  "interpretation_note",
];

function csvCell(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function buildAndVerify(rows, outputPath) {
  if (!Array.isArray(rows) || rows.length !== 56) {
    throw new Error(`D1c Fmask table requires 56 rows; found ${rows?.length ?? 0}`);
  }
  const keys = new Set(
    rows.map((row) => `${row.city}|${row.year}|${row.season_window}|${row.sensor}`),
  );
  if (keys.size !== 56 || rows.some((row) => row.record_role !== "required_hls_stratum")) {
    throw new Error("D1c Fmask required-grid roles or keys are invalid");
  }
  for (const row of rows) {
    const missing = HEADERS.filter((header) => !(header in row));
    if (missing.length) throw new Error(`D1c row lacks columns: ${missing.join(",")}`);
  }

  const matrix = [HEADERS, ...rows.map((row) => HEADERS.map((header) => row[header]))];
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("D1c Lead Lag");
  sheet.getRangeByIndexes(0, 0, matrix.length, HEADERS.length).values = matrix;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(`A1:N${matrix.length}`).format = {
    font: { name: "Arial", size: 10, color: "#183642" },
  };
  sheet.getRange("A1:N1").format = {
    fill: "#183642",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#8FA5AE" },
  };
  sheet.getRange(`A2:N${matrix.length}`).format = {
    borders: { preset: "inside", style: "thin", color: "#E1E8EB" },
  };
  sheet.getRange(`H2:H${matrix.length}`).format.numberFormat = "0.0%";
  sheet.getRange(`F2:G${matrix.length}`).format.numberFormat = "0";
  sheet.getRange(`I2:L${matrix.length}`).format.numberFormat = "0.0";
  sheet.getRange(`M2:N${matrix.length}`).format.wrapText = true;
  const widths = [27, 14, 8, 23, 22, 14, 28, 14, 24, 25, 26, 26, 34, 68];
  for (let col = 0; col < widths.length; col += 1) {
    sheet.getRangeByIndexes(0, col, matrix.length, 1).format.columnWidth = widths[col];
  }
  sheet.getRange("A1:N1").format.rowHeight = 50;
  sheet.getRange(`A2:N${matrix.length}`).format.rowHeight = 28;

  const authored = sheet.getRangeByIndexes(0, 0, matrix.length, HEADERS.length).values;
  const csv = `${authored.map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, csv, "utf8");

  const imported = await Workbook.fromCSV(csv, { sheetName: "D1c verify" });
  const verified = imported.worksheets
    .getItemAt(0)
    .getRangeByIndexes(0, 0, matrix.length, HEADERS.length).values;
  if (verified.length !== 57 || verified[0].join("|") !== HEADERS.join("|")) {
    throw new Error("Artifact-tool CSV round-trip verification failed");
  }
  const inspection = await workbook.inspect({
    kind: "table",
    range: "D1c Lead Lag!A1:N7",
    include: "values,formulas",
    tableMaxRows: 7,
    tableMaxCols: 14,
  });
  if (!inspection.ndjson.includes("required_hls_stratum")) {
    throw new Error("Artifact-tool key-range inspection failed");
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "D1c Fmask table formula-error scan",
  });
  const preview = await workbook.render({
    sheetName: "D1c Lead Lag",
    range: "A1:H8",
    scale: 1,
    format: "png",
  });
  const previewPath = process.env.D1C_FMASK_TABLE_PREVIEW || "/private/tmp/d1c_fmask_table_preview.png";
  fs.writeFileSync(previewPath, Buffer.from(await preview.arrayBuffer()));
  return {
    rows: 56,
    columns: HEADERS.length,
    unique_required_keys: keys.size,
    round_trip_verified: true,
    key_range_inspected: true,
    formula_error_scan_completed: Boolean(errors.ndjson),
    visual_preview_rendered: true,
    preview_path: previewPath,
  };
}

if (process.argv.length !== 4) {
  throw new Error("Usage: node build_v6_2_d1c_fmask_table.mjs ANALYSIS_JSON OUTPUT_CSV");
}

const analysis = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const result = await buildAndVerify(analysis.table_rows, process.argv[3]);
console.log(JSON.stringify(result));
