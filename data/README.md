# data/

All datasets used by the protocol. The `raw/`, `interim/`, and `processed/`
subfolders are git-ignored — only this README, the subfolder READMEs, and
`manifest.csv` are tracked.

`manifest.csv` is the single source of truth for provenance. Every downloaded
file is logged with: `source,dataset,filename,download_date,checksum`.
