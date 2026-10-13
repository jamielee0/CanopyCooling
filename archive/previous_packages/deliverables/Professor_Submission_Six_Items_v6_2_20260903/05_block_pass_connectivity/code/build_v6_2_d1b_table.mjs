import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { Workbook } = require("@oai/artifact-tool");

function csvCell(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function authorAndVerify(rows, outputPath) {
  if (!Array.isArray(rows) || rows.length !== 8) {
    throw new Error(`D1b requires exactly eight rows; found ${rows?.length ?? 0}`);
  }
  const headers = Object.keys(rows[0]);
  const required = [
    "city",
    "season_window",
    "view_zenith_set_deg",
    "eligible_blocks",
    "eligible_passes",
    "block_passes",
    "median_passes_per_block",
    "p10_passes_per_block",
    "blocks_below_floor",
    "largest_connected_component_share",
    "spatial_sectors",
    "sectors_represented",
    "dominant_land_use_class",
    "largest_share_one_land_use_class",
    "combination_pass",
  ];
  if (headers.join("|") !== required.join("|")) {
    throw new Error(`D1b columns differ from frozen order: ${headers.join(",")}`);
  }
  const keys = new Set();
  for (const row of rows) {
    if (Object.keys(row).join("|") !== headers.join("|")) {
      throw new Error("D1b rows have inconsistent column order");
    }
    keys.add(`${row.city}|${row.season_window}|${row.view_zenith_set_deg}`);
  }
  if (keys.size !== 8) throw new Error("D1b combination keys are not unique");

  const matrix = [headers, ...rows.map((row) => headers.map((header) => row[header]))];
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("D1b Connectivity");
  sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values = matrix;
  const authored = sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values;
  const csv = `${authored.map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, csv, "utf8");

  const imported = await Workbook.fromCSV(csv, { sheetName: "D1b verify" });
  const verified = imported.worksheets
    .getItemAt(0)
    .getRangeByIndexes(0, 0, matrix.length, headers.length).values;
  if (verified.length !== 9 || verified[0].join("|") !== headers.join("|")) {
    throw new Error("Artifact-tool CSV round-trip verification failed");
  }
  return { rows: 8, columns: headers.length, unique_combinations: keys.size };
}

if (process.argv.length !== 4) {
  throw new Error("Usage: node build_v6_2_d1b_table.mjs ANALYSIS_JSON OUTPUT_CSV");
}

const analysis = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const result = await authorAndVerify(analysis.summary_rows, process.argv[3]);
console.log(JSON.stringify(result));
