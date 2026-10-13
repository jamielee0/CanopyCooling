# D1d — Stage 1 precision census

Status: **STOP — no estimable block-pass under the frozen canopy-span rule.**

The five metadata-selected, already-downloaded Phoenix passes produced 13,210
candidate block-passes with at least 60 complete native cells. Every candidate has
canopy p10–p90 span below the frozen 0.20 floor (observed maximum 0.185551), so the
calculation stopped before any block-specific coefficient or spatial standard error
was calculated. Gate A remains unauthorized.

## Deliverables

- `memo.pdf` — two-page decision memo.
- `tables/d1d_stage1_se.csv` — 13,210 open candidate rows; no point estimates.
- `tables/d1d_n_required.csv` — all 48 D1b combination × reliability × criterion
  rows. Observed sigma and required N are explicitly not estimable.
- `figures/d1d_se_distribution.png` / `.svg` — no-SE state plus the canopy-span
  failure distribution.
- `figures/d1d_n_required.png` / `.svg` — hypothetical closed-form planning curves;
  no observed-SE marker.
- `sealed/d1d_coefficients_SEALED.csv` — link to the canonical guarded sealed file.
  It contains a header and zero coefficient rows.
- `analysis_manifest.json` — source hashes, count identities, rule result and sealed
  checksum.
- `sealed_file_pointer.json` — canonical path and checksum only.
- `data/d1d_analysis_rows.json` — open analysis records used to author the tables.
- `data/artifact_tool_verification.json` — CSV round-trip and visual-preview checks.
- `checksums.txt` — package checksums.
- `code_commit.txt` — exact commands and current repository state.

## Interpretation boundary

This is a valid failed free check, not an estimate of tree-cooling direction or
magnitude. The run used explicitly disclosed precision-only proxies: Collection-2
LST, inherited modified-NLCD canopy, LSTE height, NLCD water distance, and a 10 m
building-fraction approximation. These inputs cannot become the final v6.2 study
stack. Raw annual Science TCC should be obtained and screened nonthermally before any
further thermal run.

The sealed file checksum is
`146b16f85aa89c486d174121d1e3e781ded685d8940f0dc6037e238b090d6004`.
It was hashed, not opened, after creation.

