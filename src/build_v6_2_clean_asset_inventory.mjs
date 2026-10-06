#!/usr/bin/env node
/** Build a professor-facing workbook containing only raw-asset inventory content. */

import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";


function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    args[argv[i].replace(/^--/, "")] = argv[i + 1];
  }
  return args;
}


async function saveRender(workbook, sheetName, range, outputPath) {
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1.5,
    format: "png",
  });
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, new Uint8Array(await preview.arrayBuffer()));
}


const args = parseArgs(process.argv);
if (!args.source || !args["preview-dir"]) {
  throw new Error("Required: --source INPUT.xlsx --preview-dir DIR [--output OUTPUT.xlsx]");
}

const sourceBlob = await FileBlob.load(args.source);
const source = await SpreadsheetFile.importXlsx(sourceBlob);

if (!args.output) {
  await saveRender(
    source,
    "Asset Status & Gaps",
    "A1:D14",
    path.join(args["preview-dir"], "source_asset_status.png"),
  );
  await saveRender(
    source,
    "Verified Files",
    "A1:J24",
    path.join(args["preview-dir"], "source_verified_files_top.png"),
  );
  process.stdout.write(JSON.stringify({ mode: "source-preview", previewDir: args["preview-dir"] }, null, 2));
  process.stdout.write("\n");
  process.exit(0);
}

const statusValues = source.worksheets
  .getItem("Asset Status & Gaps")
  .getRange("A1:D14").values;
const verifiedValues = source.worksheets
  .getItem("Verified Files")
  .getRange("A1:J168").values;

const workbook = Workbook.create();
const statusSheet = workbook.worksheets.add("Asset Status");
const filesSheet = workbook.worksheets.add("Verified Files");

statusSheet.getRange("A1:D14").values = statusValues;
statusSheet.mergeCells("A1:D1");
statusSheet.mergeCells("A2:D2");
statusSheet.showGridLines = false;
statusSheet.freezePanes.freezeRows(3);
statusSheet.getRange("A1:D1").format = {
  fill: "#17324D",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  verticalAlignment: "center",
};
statusSheet.getRange("A2:D2").format = {
  fill: "#EAF4F8",
  font: { color: "#334155", italic: true },
  wrapText: true,
  verticalAlignment: "center",
};
statusSheet.getRange("A3:D3").format = {
  fill: "#0E7490",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
  verticalAlignment: "center",
};
statusSheet.getRange("A4:D14").format = {
  font: { color: "#1F2937" },
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "inside", style: "thin", color: "#CBD5E1" },
};
statusSheet.getRange("A1:D14").format.font.name = "Aptos";
statusSheet.getRange("A1:D14").format.font.size = 10;
statusSheet.getRange("A1:D1").format.font.size = 16;
statusSheet.getRange("A1").format.columnWidth = 31;
statusSheet.getRange("B1").format.columnWidth = 23;
statusSheet.getRange("C1").format.columnWidth = 61;
statusSheet.getRange("D1").format.columnWidth = 61;
statusSheet.getRange("1:1").format.rowHeight = 28;
statusSheet.getRange("2:2").format.rowHeight = 34;
statusSheet.getRange("3:3").format.rowHeight = 28;
statusSheet.getRange("4:14").format.rowHeight = 48;
statusSheet.tables.add("A3:D14", true, "AssetStatusTable");

const statusColors = {
  "ACQUIRED / VERIFIED": "#E8F5E9",
  ACQUIRED: "#E8F5E9",
  "DEFERRED TO GATE A": "#FFF4D6",
  "CATALOGUE ONLY / INCOMPLETE": "#FFF4D6",
  "PARTIAL / HISTORICAL": "#FFF4D6",
  "NOT ACQUIRED": "#FDECEC",
  "PARTIAL / RECOVERED": "#FFF4D6",
  "PARTIAL / CONTEXT ONLY": "#FFF4D6",
  "PARTIAL / UNRESOLVED": "#FFF4D6",
};
for (let row = 4; row <= 14; row += 1) {
  const value = statusSheet.getRange(`B${row}`).values[0][0];
  statusSheet.getRange(`B${row}`).format = {
    fill: statusColors[value] ?? "#FFFFFF",
    font: { bold: true, color: "#334155" },
    wrapText: true,
    verticalAlignment: "top",
  };
}

filesSheet.getRange("A1:J168").values = verifiedValues;
filesSheet.mergeCells("A1:J1");
filesSheet.mergeCells("A2:J2");
filesSheet.showGridLines = false;
filesSheet.freezePanes.freezeRows(3);
filesSheet.getRange("A1:J1").format = {
  fill: "#17324D",
  font: { bold: true, color: "#FFFFFF", name: "Aptos", size: 16 },
  verticalAlignment: "center",
};
filesSheet.getRange("A2:J2").format = {
  fill: "#EAF4F8",
  font: { color: "#334155", italic: true, name: "Aptos", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
filesSheet.getRange("A3:J3").format = {
  fill: "#0E7490",
  font: { bold: true, color: "#FFFFFF", name: "Aptos", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
filesSheet.getRange("A4:J168").format = {
  font: { color: "#1F2937", name: "Aptos", size: 9 },
  verticalAlignment: "top",
  borders: { preset: "inside", style: "thin", color: "#E5E7EB" },
};
filesSheet.getRange("F4:F168").format.numberFormat = "#,##0";
const widths = [22, 16, 14, 48, 25, 14, 64, 34, 72, 72];
for (let col = 0; col < widths.length; col += 1) {
  filesSheet.getCell(0, col).format.columnWidth = widths[col];
}
filesSheet.getRange("1:1").format.rowHeight = 28;
filesSheet.getRange("2:2").format.rowHeight = 34;
filesSheet.getRange("3:3").format.rowHeight = 30;
filesSheet.getRange("4:168").format.rowHeight = 20;
filesSheet.tables.add("A3:J168", true, "VerifiedFilesTable");

await saveRender(
  workbook,
  "Asset Status",
  "A1:D14",
  path.join(args["preview-dir"], "clean_asset_status.png"),
);
await saveRender(
  workbook,
  "Verified Files",
  "A1:J24",
  path.join(args["preview-dir"], "clean_verified_files_top.png"),
);

const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});

await fs.mkdir(path.dirname(args.output), { recursive: true });
const outputBlob = await SpreadsheetFile.exportXlsx(workbook);
await outputBlob.save(args.output);

process.stdout.write(JSON.stringify({
  mode: "build",
  output: args.output,
  statusRows: statusValues.length - 3,
  verifiedFileRows: verifiedValues.length - 3,
  errorScan: errorScan.ndjson,
  previewDir: args["preview-dir"],
}, null, 2));
process.stdout.write("\n");
