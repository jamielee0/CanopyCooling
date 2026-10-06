import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { FileBlob, SpreadsheetFile, Workbook } = require("@oai/artifact-tool");

if (process.argv.length !== 7) {
  throw new Error(
    "Usage: node build_v6_2_initial_package_workbook.mjs HLS_JSON TCC_JSON DEP_JSON PACKAGE_INDEX_JSON OUTPUT_XLSX",
  );
}

const [hlsPath, tccPath, depPath, packageIndexPath, outputPath] = process.argv.slice(2);
const hls = JSON.parse(fs.readFileSync(hlsPath, "utf8"));
const tcc = JSON.parse(fs.readFileSync(tccPath, "utf8"));
const dep = JSON.parse(fs.readFileSync(depPath, "utf8"));
const packageIndex = JSON.parse(fs.readFileSync(packageIndexPath, "utf8"));

function cityLabel(value) {
  if (!value) return "";
  return value
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

const verifiedRows = [];
for (const item of hls.files) {
  verifiedRows.push([
    "HLS V2 Fmask",
    cityLabel(item.city),
    String(item.source_time || "").slice(0, 10),
    path.basename(item.local_path),
    item.status === "VERIFIED_EXISTING" ? "ACQUIRED / VERIFIED" : item.status,
    item.bytes,
    item.sha256,
    "",
    item.local_path,
    item.source_url,
  ]);
}
for (const item of tcc.files) {
  const match = item.name.match(/_(phoenix|los_angeles)_(\d{4})_/);
  verifiedRows.push([
    "Science TCC v2025-6",
    cityLabel(match?.[1] || ""),
    match?.[2] || "",
    item.name,
    item.download_verified ? "ACQUIRED / VERIFIED" : "VERIFY",
    item.bytes,
    item.local_sha256,
    item.local_md5,
    item.local_path,
    item.drive_url,
  ]);
}
for (const item of dep.files) {
  const match = item.name.match(/_(phoenix|los_angeles)_/);
  verifiedRows.push([
    "USGS 3DEP 10 m",
    cityLabel(match?.[1] || ""),
    "snapshot through 2022-05-04",
    item.name,
    item.download_verified ? "ACQUIRED / VERIFIED" : "VERIFY",
    item.bytes,
    item.local_sha256,
    item.local_md5,
    item.local_path,
    item.drive_url,
  ]);
}

if (verifiedRows.length !== 165) {
  throw new Error(`Expected 165 verified files; found ${verifiedRows.length}`);
}

const gapsRows = [
  ["HLS V2 Fmask", "ACQUIRED / VERIFIED", "149 files; exact SHA-256 manifest match", "None pre-Gate A"],
  ["HLS V2 reflectance", "DEFERRED TO GATE A", "Not opened or downloaded for this closeout", "Acquire required reflectance bands only after Gate A authorization"],
  ["Science TCC v2025-6", "ACQUIRED / VERIFIED", "14 files; Phoenix and Los Angeles, 2019–2025; cover and SE; per-file SHA-256/MD5/bytes", "None for the nonthermal canopy-span screen"],
  ["USGS 3DEP 10 m", "ACQUIRED / VERIFIED", "2 frozen-domain files; per-file SHA-256/MD5/bytes; Earth Engine snapshot ends 2022-05-04", "Supervisor may request a newer USGS tile-state refresh"],
  ["ECOSTRESS Collection 3", "CATALOGUE ONLY / INCOMPLETE", "Independent CMR catalogue evidence retained; no new thermal values opened", "Acquire approved Collection 3 thermal products after Gate A"],
  ["HRRR / weather", "PARTIAL / HISTORICAL", "219 passes, 438 joins, 413 historical assets; 10/10 sampled joins passed", "Reacquire/freeze final study-sample weather after Gate A"],
  ["Precipitation", "NOT ACQUIRED", "No frozen pre-Gate A precipitation payload", "Select exact product/release/years and acquire before dependent analysis"],
  ["Census urban areas / frozen blocks", "ACQUIRED", "Frozen domain and 1 km analysis geometry available", "No immediate gap"],
  ["L1B viewing geometry", "PARTIAL / RECOVERED", "762 rows checked; 734 reconstruction artifacts verified; archive gaps documented", "Resolve final Collection 3 geometry completeness for study sample"],
  ["Land use / land cover", "PARTIAL / CONTEXT ONLY", "Annual NLCD used only as inherited connectivity context; not accepted as the canopy exposure", "Freeze final contextual release if retained after Gate A"],
  ["Remaining context", "PARTIAL / UNRESOLVED", "Context assets exist unevenly across inherited work", "Supervisor-approved inventory freeze needed before dependent modelling"],
];

const packageRows = packageIndex.items.map((item) => [
  item.item,
  item.status,
  item.path,
  item.purpose,
]);

const wb = Workbook.create();
const summary = wb.worksheets.add("Summary");
const verified = wb.worksheets.add("Verified Files");
const gaps = wb.worksheets.add("Asset Status & Gaps");
const pkg = wb.worksheets.add("Package Index");

const navy = "#17324D";
const teal = "#0E7490";
const paleBlue = "#EAF4F8";
const paleGreen = "#E8F5E9";
const paleAmber = "#FFF4D6";
const paleRed = "#FDECEC";
const border = "#CBD5E1";
const white = "#FFFFFF";

function titleBand(sheet, range, title, subtitle) {
  sheet.getRange(range).merge();
  const start = range.split(":")[0];
  sheet.getRange(start).values = [[title]];
  sheet.getRange(range).format = {
    fill: navy,
    font: { color: white, bold: true, size: 18 },
    verticalAlignment: "center",
    horizontalAlignment: "left",
  };
  sheet.getRange(range).format.rowHeight = 34;
  const subtitleRange = sheet.getRange(`A2:${range.split(":")[1].replace(/\d+/, "2")}`);
  subtitleRange.merge();
  subtitleRange.values = [[subtitle]];
  subtitleRange.format = {
    fill: paleBlue,
    font: { color: navy, italic: true, size: 10 },
    wrapText: true,
    verticalAlignment: "center",
  };
  subtitleRange.format.rowHeight = 30;
  sheet.showGridLines = false;
}

function styleHeader(range) {
  range.format = {
    fill: teal,
    font: { color: white, bold: true },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: border },
  };
  range.format.rowHeight = 28;
}

titleBand(
  summary,
  "A1:D1",
  "Urban Tree Cooling v6.2 — Pre-Gate A Inventory",
  "Verified 2026-09-02. File counts and bytes below are formulas linked to the per-file evidence sheet.",
);
summary.getRange("A4:B10").values = [
  ["Metric", "Verified value"],
  ["Total acquired files", null],
  ["Total acquired bytes", null],
  ["HLS Fmask files", null],
  ["Science TCC files", null],
  ["3DEP files", null],
  ["All locally hashed", null],
];
styleHeader(summary.getRange("A4:B4"));
summary.getRange("B5").formulas = [["=COUNTA('Verified Files'!A4:A168)"]];
summary.getRange("B6").formulas = [["=SUM('Verified Files'!F4:F168)"]];
summary.getRange("B7").formulas = [["=COUNTIF('Verified Files'!A4:A168,\"HLS V2 Fmask\")"]];
summary.getRange("B8").formulas = [["=COUNTIF('Verified Files'!A4:A168,\"Science TCC v2025-6\")"]];
summary.getRange("B9").formulas = [["=COUNTIF('Verified Files'!A4:A168,\"USGS 3DEP 10 m\")"]];
summary.getRange("B10").formulas = [["=IF(COUNTIF('Verified Files'!G4:G168,\"\")=0,\"YES\",\"NO\")"]];
summary.getRange("B6").format.numberFormat = "#,##0";
summary.getRange("A5:B10").format.borders = { preset: "all", style: "thin", color: border };
summary.getRange("A12:D12").merge();
summary.getRange("A12").values = [["Decision snapshot"]];
summary.getRange("A12:D12").format = { fill: navy, font: { color: white, bold: true } };
summary.getRange("A13:D19").values = [
  ["Area", "Current status", "Evidence", "Immediate consequence"],
  ["Foundation audit", "PASS", "31/31 required checks pass", "Foundation evidence is ready for supervisor sign-off"],
  ["Connectivity", "PASS FOR PLANNING", "15° historical proxy supports planning; geometry limitations remain", "Does not itself authorize Gate A"],
  ["Lead–lag", "EXPLORATORY / DEMOTED", "Inherited centred HLS feasibility product lacks final exposure provenance", "Rebuild after Gate A if retained"],
  ["VPD branch", "INACTIVE HOLD", "Strict D003 fails both cities; D005 passes Phoenix but Los Angeles support width is 0.300 < 0.500 kPa", "Supervisor keep/drop/amend ruling required before activation"],
  ["Stage 1", "STOP", "Official Science TCC: 0 of 13,509 block-passes meet p10–p90 ≥ 0.20; max 0.18410", "No thermal rerun; no new coefficient opened"],
  ["Gate A", "DO NOT BEGIN AS WRITTEN", "Required canopy exposure contrast is absent in the five-pass test under the frozen rule", "Supervisor must stop, reframe, or prospectively amend the design"],
];
styleHeader(summary.getRange("A13:D13"));
summary.getRange("A14:D19").format = {
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "all", style: "thin", color: border },
};
summary.getRange("B14:B15").format.fill = paleGreen;
summary.getRange("B16:B17").format.fill = paleAmber;
summary.getRange("B18:B19").format.fill = paleRed;
summary.getRange("A1:D19").format.font = { name: "Aptos" };
summary.getRange("A:A").format.columnWidth = 25;
summary.getRange("B:B").format.columnWidth = 22;
summary.getRange("C:C").format.columnWidth = 62;
summary.getRange("D:D").format.columnWidth = 52;
summary.getRange("A13:D19").format.autofitRows();
summary.freezePanes.freezeRows(3);

titleBand(
  verified,
  "A1:J1",
  "Verified per-file evidence",
  "165 acquired files. SHA-256 is local; MD5 is included for Drive-hosted TCC and 3DEP outputs and matched Google metadata.",
);
const verifiedHeaders = [["Asset group", "City", "Year / date", "File name", "Status", "Bytes", "SHA-256", "MD5", "Local path", "Source / Drive URL"]];
verified.getRange("A3:J3").values = verifiedHeaders;
verified.getRangeByIndexes(3, 0, verifiedRows.length, 10).values = verifiedRows;
styleHeader(verified.getRange("A3:J3"));
verified.getRange(`A4:J${verifiedRows.length + 3}`).format = {
  wrapText: false,
  verticalAlignment: "top",
  borders: { preset: "all", style: "thin", color: border },
};
verified.getRange(`F4:F${verifiedRows.length + 3}`).format.numberFormat = "#,##0";
const widths = [24, 16, 24, 54, 22, 15, 70, 36, 80, 74];
for (let i = 0; i < widths.length; i += 1) {
  verified.getRangeByIndexes(0, i, verifiedRows.length + 3, 1).format.columnWidth = widths[i];
}
verified.freezePanes.freezeRows(3);
verified.freezePanes.freezeColumns(4);

titleBand(
  gaps,
  "A1:D1",
  "Consolidated asset inventory",
  "Missing data are recorded as inventory findings; acquisition is not implied unless explicitly authorized by the gate decision.",
);
gaps.getRange("A3:D3").values = [["Product / context", "Status", "Evidence in hand", "Remaining action"]];
gaps.getRangeByIndexes(3, 0, gapsRows.length, 4).values = gapsRows;
styleHeader(gaps.getRange("A3:D3"));
gaps.getRange(`A4:D${gapsRows.length + 3}`).format = {
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "all", style: "thin", color: border },
};
gaps.getRange("A:A").format.columnWidth = 30;
gaps.getRange("B:B").format.columnWidth = 27;
gaps.getRange("C:C").format.columnWidth = 65;
gaps.getRange("D:D").format.columnWidth = 62;
gaps.getRange(`A3:D${gapsRows.length + 3}`).format.autofitRows();
gaps.freezePanes.freezeRows(3);

titleBand(
  pkg,
  "A1:D1",
  "Initial-package index",
  "Paths are repository-relative. Status reflects package assembly, not supervisor approval.",
);
pkg.getRange("A3:D3").values = [["Item", "Status", "Repository path", "Purpose"]];
pkg.getRangeByIndexes(3, 0, packageRows.length, 4).values = packageRows;
styleHeader(pkg.getRange("A3:D3"));
pkg.getRange(`A4:D${packageRows.length + 3}`).format = {
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "all", style: "thin", color: border },
};
pkg.getRange("A:A").format.columnWidth = 33;
pkg.getRange("B:B").format.columnWidth = 24;
pkg.getRange("C:C").format.columnWidth = 84;
pkg.getRange("D:D").format.columnWidth = 62;
pkg.getRange(`A3:D${packageRows.length + 3}`).format.autofitRows();
pkg.freezePanes.freezeRows(3);

const formulaScan = await wb.inspect({
  kind: "formula",
  sheetId: "Summary",
  range: "A1:D19",
  maxChars: 5000,
});
const summaryRegion = await wb.inspect({
  kind: "region",
  sheetId: "Summary",
  range: "A1:D19",
  maxChars: 8000,
});
const output = await SpreadsheetFile.exportXlsx(wb);
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);

const reloaded = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const reloadedSummary = reloaded.worksheets.getItem("Summary").getRange("B5:B10").values.flat();
const expectedSummary = [165, 800091676, 149, 14, 2, "YES"];
if (JSON.stringify(reloadedSummary) !== JSON.stringify(expectedSummary)) {
  throw new Error(
    `Reloaded summary mismatch: ${JSON.stringify(reloadedSummary)} != ${JSON.stringify(expectedSummary)}`,
  );
}

const renderDir = path.join(path.dirname(outputPath), "_workbook_previews");
fs.mkdirSync(renderDir, { recursive: true });
for (const sheetName of ["Summary", "Verified Files", "Asset Status & Gaps", "Package Index"]) {
  const preview = await wb.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  const bytes = new Uint8Array(await preview.arrayBuffer());
  await fs.promises.writeFile(path.join(renderDir, `${sheetName.replaceAll(" ", "_")}.png`), bytes);
}

console.log(JSON.stringify({
  output: outputPath,
  verified_files: verifiedRows.length,
  verified_bytes: verifiedRows.reduce((total, row) => total + row[5], 0),
  package_items: packageRows.length,
  reloaded_summary: reloadedSummary,
  formula_scan: formulaScan.ndjson,
  summary_region: summaryRegion.ndjson,
}));
