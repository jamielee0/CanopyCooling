import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { Workbook } = require("@oai/artifact-tool");

const STAGE_HEADERS = [
  "city",
  "block_id",
  "pass_id",
  "valid_cell_count",
  "canopy_span_p10_p90",
  "mean_canopy_fraction",
  "spatially_robust_se_K_per_10pp",
  "max_hat_leverage",
  "leverage_threshold",
  "high_leverage_flag",
  "residual_morans_i",
  "cardinal_neighbor_pairs",
  "context_terms_retained",
  "spatial_replicates_successful",
  "max_quadrant_canopy_information_share",
  "estimability_flag",
  "convergence_flag",
  "design_stability_flag",
  "failure_reason",
];

const POWER_HEADERS = [
  "city",
  "season_window",
  "view_zenith_set_deg",
  "se_summary",
  "observed_stage1_se_K_per_10pp",
  "reliability",
  "criterion",
  "attenuated_target_K_per_10pp",
  "required_connected_block_passes",
  "available_connected_block_passes_D1b",
  "status",
];

const FORBIDDEN_OPEN_FIELDS = [
  "slope_K_per_unit_canopy_fraction",
  "CE_K_per_10pp",
];

function csvCell(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function normalizedValue(header, value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" && !Number.isInteger(value)) {
    return Number(value.toFixed(6));
  }
  return value;
}

async function writeCsvWithArtifactTool(rows, headers, sheetName, outputPath, previewPath) {
  const matrix = [
    headers,
    ...rows.map((row) => headers.map((header) => normalizedValue(header, row[header]))),
  ];
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(sheetName);
  sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values = matrix;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
    fill: "#183642",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#CBD8DD" },
  };
  const previewRows = Math.min(matrix.length, 18);
  sheet.getRangeByIndexes(0, 0, previewRows, headers.length).format.autofitColumns();
  sheet.getRangeByIndexes(0, 0, previewRows, headers.length).format.autofitRows();
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format.rowHeight = 48;
  const authored = sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values;
  const csv = `${authored.map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, csv, "utf8");

  const imported = await Workbook.fromCSV(csv, { sheetName: `${sheetName} verify` });
  const verified = imported.worksheets
    .getItemAt(0)
    .getRangeByIndexes(0, 0, matrix.length, headers.length).values;
  if (verified.length !== matrix.length || verified[0].join("|") !== headers.join("|")) {
    throw new Error(`${sheetName} artifact-tool CSV round trip failed`);
  }
  const inspected = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!A1:${String.fromCharCode(64 + Math.min(headers.length, 26))}${Math.min(6, matrix.length)}`,
    include: "values,formulas",
    tableMaxRows: 6,
    tableMaxCols: headers.length,
  });
  if (!inspected.ndjson.includes(headers[0])) {
    throw new Error(`${sheetName} key-range inspection failed`);
  }
  const rendered = await workbook.render({
    sheetName,
    range: `A1:${String.fromCharCode(64 + Math.min(headers.length, 26))}${previewRows}`,
    scale: 0.75,
    format: "png",
  });
  fs.writeFileSync(previewPath, Buffer.from(await rendered.arrayBuffer()));
  return { rows: rows.length, columns: headers.length, roundTripVerified: true, inspected: true, rendered: true };
}

if (process.argv.length !== 7) {
  throw new Error("Usage: node build_v6_2_d1d_tables.mjs ANALYSIS_JSON STAGE_CSV POWER_CSV VERIFICATION_JSON PREVIEW_DIR");
}

const [analysisPath, stagePath, powerPath, verificationPath, previewDir] = process.argv.slice(2);
const analysis = JSON.parse(fs.readFileSync(analysisPath, "utf8"));
const stageRows = analysis.stage1_rows;
const powerRows = analysis.power_rows;
if (!Array.isArray(stageRows) || stageRows.length === 0) throw new Error("D1d Stage-1 rows are empty");
if (!Array.isArray(powerRows) || powerRows.length === 0) throw new Error("D1d power rows are empty");
for (const row of [...stageRows, ...powerRows]) {
  for (const field of FORBIDDEN_OPEN_FIELDS) {
    if (Object.hasOwn(row, field)) throw new Error(`Open D1d data contains forbidden point-estimate field ${field}`);
  }
}
if (stageRows.length !== 13210) throw new Error(`Frozen run expected 13,210 Stage-1 rows; found ${stageRows.length}`);
if (powerRows.length !== 48) throw new Error(`Frozen no-estimability run expected 48 power rows; found ${powerRows.length}`);
if (!stageRows.every((row) => row.convergence_flag === false && row.failure_reason === "canopy_span_below_0_20")) {
  throw new Error("Stage-1 no-estimability identity failed");
}
if (!powerRows.every((row) => row.required_connected_block_passes === null)) {
  throw new Error("No-estimability power table must not invent required counts");
}

fs.mkdirSync(previewDir, { recursive: true });
const stageResult = await writeCsvWithArtifactTool(
  stageRows,
  STAGE_HEADERS,
  "D1d Stage1 SE",
  stagePath,
  path.join(previewDir, "d1d_stage1_preview.png"),
);
const powerResult = await writeCsvWithArtifactTool(
  powerRows,
  POWER_HEADERS,
  "D1d N Required",
  powerPath,
  path.join(previewDir, "d1d_power_preview.png"),
);
const verification = {
  stageTable: stageResult,
  powerTable: powerResult,
  pointEstimateFieldsAbsent: true,
  allStageRowsFailFrozenSpan: true,
  requiredCountsRemainBlankWhenSigmaNotEstimable: true,
};
fs.mkdirSync(path.dirname(verificationPath), { recursive: true });
fs.writeFileSync(verificationPath, `${JSON.stringify(verification, null, 2)}\n`, "utf8");
console.log(JSON.stringify(verification));

