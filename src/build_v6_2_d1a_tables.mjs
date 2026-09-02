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

async function authorAndVerifyCsv(rows, outputPath, sheetName) {
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(`${sheetName}: no rows supplied`);
  }
  const headers = Object.keys(rows[0]);
  for (const row of rows) {
    const keys = Object.keys(row);
    if (keys.length !== headers.length || !headers.every((key, index) => key === keys[index])) {
      throw new Error(`${sheetName}: inconsistent column order`);
    }
  }

  const matrix = [headers, ...rows.map((row) => headers.map((header) => row[header]))];
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(sheetName);
  sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values = matrix;

  const authored = sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values;
  const csv = `${authored.map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, csv, "utf8");

  const imported = await Workbook.fromCSV(csv, { sheetName: `${sheetName}_verify` });
  const verified = imported.worksheets
    .getItemAt(0)
    .getRangeByIndexes(0, 0, matrix.length, headers.length).values;
  if (verified.length !== matrix.length || verified[0].length !== headers.length) {
    throw new Error(`${sheetName}: CSV verification dimensions do not match`);
  }
  if (verified[0].join("|") !== headers.join("|")) {
    throw new Error(`${sheetName}: CSV verification header mismatch`);
  }
  return { rows: rows.length, columns: headers.length };
}

if (process.argv.length !== 5) {
  throw new Error(
    "Usage: node build_v6_2_d1a_tables.mjs ANALYSIS_JSON PAIRWISE_CSV CONDITION_CSV",
  );
}

const analysis = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const pairwise = await authorAndVerifyCsv(
  analysis.pairwise_rows,
  process.argv[3],
  "Pairwise",
);
const condition = await authorAndVerifyCsv(
  analysis.condition_rows,
  process.argv[4],
  "ConditionIndex",
);
console.log(JSON.stringify({ pairwise, condition }));
