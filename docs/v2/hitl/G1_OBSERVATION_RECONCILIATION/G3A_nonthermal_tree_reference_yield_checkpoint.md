# Mandatory later checkpoint — G3A nonthermal tree/reference yield

**Status:** `PLANNED_NOT_AUTHORIZED`  
**Placement:** after G3 freezes the sampling design and before G4, G5, or G7

## Purpose

Resolve the tree/reference evidence gap without inspecting temperature values. For every
G3-selected physical pass, compute pre-outcome eligible tree pixels, reference pixels, and
nonthermal matching yield.

## Permitted inputs

- the G3-frozen city, season, and view-angle design;
- checksum-bound tree/canopy, imperviousness, land-cover, water, building/buffer, and
  neighborhood masks;
- frozen geometry and cloud/fill masks; and
- a separately named retrieval-validity/QA layer only if the temperature/LST value band is
  technically blocked and never opened.

## Required outputs

- raw candidate tree and reference pixel counts per physical pass;
- counts after every nonthermal eligibility rule;
- eligible neighborhood and matched-set counts per pass;
- zero-yield and low-yield pass flags;
- physical pass counts beside all exposure summaries; and
- hashes proving that no temperature/LST value layer was accessed.

## Guardrails

No temperature/LST value, thermal outcome, 2026 record, or holdout outcome may be opened.
The checkpoint must stop for human approval. Its counts are pre-outcome eligibility/yield
counts, not cooling-contrast reliability estimates and not independent weather sample sizes.
