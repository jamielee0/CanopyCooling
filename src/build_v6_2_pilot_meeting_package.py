from pathlib import Path
import json,pandas as pd,numpy as np,hashlib,shutil,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'deliverables/Pilot_Meeting_Package_v6_2_20260919';OUT.mkdir(parents=True,exist_ok=True)
public=ROOT/'outputs/v6_2/scientific';execution=ROOT/'docs/v2/v6_2/execution';synthetic=ROOT/'tests/fixtures/synthetic_demo/mixing_20260919'
rows=[];stress=[];ownership=[];summaries=[];residual=[]
for city in ['phoenix','atlanta']:
 p=public/f'pooled_pilot_20260919_{city}'
 if not (p/'precision_summary.json').exists():raise ValueError(f'{city} precision run not complete')
 residual.append(pd.read_csv(p/'residual_spatial_diagnostics.csv'));rows.append(pd.read_csv(p/'precision.csv'));stress.append(pd.read_csv(p/'spatial_stress_precision.csv'));ownership.append(pd.read_csv(p/'native_ownership_audit.csv'));summaries.append(json.loads((p/'precision_summary.json').read_text()))
allprecision=pd.concat(rows);primary=allprecision[allprecision.variant=='paired_primary'].copy();larger=pd.concat(stress)
primary.to_csv(OUT/'02_two_city_precision.csv',index=False);allprecision.to_csv(OUT/'02_precision_sensitivities.csv',index=False);larger.to_csv(OUT/'02_larger_spatial_groups.csv',index=False);pd.concat(ownership).to_csv(OUT/'01_native_ownership_counts.csv',index=False)
pd.concat(residual).to_csv(OUT/'02_residual_spatial_dependence.csv',index=False)
# Only the explicit public precision outputs enter this package.
def table(frame,columns,formats=None):
 formats=formats or {};lines=['| '+' | '.join(columns)+' |','| '+' | '.join(['---']*len(columns))+' |']
 for _,r in frame.iterrows():lines.append('| '+' | '.join(format(r[c],formats[c]) if c in formats else str(r[c]) for c in columns)+' |')
 return '\n'.join(lines)
short=primary[['city','pass_id','n_cells','contributing_blocks','LST_K_SE_per_10pp','LST_K_bootstrap_width_95_per_10pp','within_block_Sxx']].copy()
short.columns=['City','Pass','Cells','Blocks with variation','SE K per 10pp','Bootstrap width K per 10pp','Within-block Sxx']
precision_table=table(short,list(short.columns),{'SE K per 10pp':'.4f','Bootstrap width K per 10pp':'.4f','Within-block Sxx':'.2f'})
summary_table=[]
for city in ['phoenix','atlanta']:
 a=primary[primary.city==city];b=larger[(larger.city==city)&(larger.variant=='spatial_8km')]
 summary_table.append({'City':city.title(),'Five-pass SE range':f'{a.LST_K_SE_per_10pp.min():.4f}–{a.LST_K_SE_per_10pp.max():.4f}','Median SE':f'{a.LST_K_SE_per_10pp.median():.4f}','8km-group SE range':f'{b.LST_K_SE_per_10pp.min():.4f}–{b.LST_K_SE_per_10pp.max():.4f}'})
main='''# v6.2 two-city pilot for precision review

The revised pooled estimator has been run for all five frozen Phoenix passes and five Atlanta passes selected before thermal download. LST and emitted-energy models use the same native cells, controls and whole-block resampling. Empirical coefficients, predictions, bootstrap endpoints and time-contrast values remain sealed. This package contains permitted precision diagnostics and clearly labeled simulations.

'''+table(pd.DataFrame(summary_table),list(summary_table[0]))+'''

SE units are kelvin per 10 percentage points of canopy. The approximate 0.10 benchmark is a feasibility reference, not a scale-agreement tolerance or a four-of-five gate. Larger spatial groups test uncertainty sensitivity; passing that benchmark does not establish a time pattern or equivalence.

The four meeting items are:

1. [Audit and sample selection](01_audit_and_sample_selection.md).
2. [All ten precision results](02_precision_and_support.md), with the accompanying CSV and sensitivity tables.
3. [Mixing test and exact conversion](03_mixing_and_standardization.md).
4. [Decisions for Reza](04_decisions_for_Reza.md).

All 280 synthetic city-pass/scenario/contrast combinations are complete. Both total-time comparisons are computed and sealed; neither city has common support for the secondary geometry/season comparison. Twenty-one targeted tests and the output-boundary check pass.

The main unresolved decisions are Reza’s numerical scale tolerance and recorded release of the empirical comparisons after precision review. Full-city expansion remains paused. The protocol stays at v6.2.
'''
(OUT/'README.md').write_text(main)
(OUT/'02_precision_and_support.md').write_text('# Precision and support for all ten city-passes\n\n'+precision_table+'\n\nThe standard errors are the SD of 1,000 paired whole-1km-block bootstrap slope draws, scaled by 0.10. The interval column is q97.5 minus q2.5; endpoints and signs are sealed. Sxx is the sum of squared within-block canopy deviations in fraction-squared units. No 0.20/0.10 canopy-span filter or arbitrary pass-information minimum is used. All finite, estimable blocks can contribute. The full CSV additionally reports residualized canopy information, information concentration, effective information blocks, rank, leverage, resample failures and emitted-energy precision in W/m² per 10 percentage points.\n\n'+table(pd.DataFrame(summary_table),list(summary_table[0]))+'\n\nFour cardinal ±1-cell shifts, an exact common-cell subset across five passes, and 2km groups are in 02_precision_sensitivities.csv. The separately frozen 4km and 8km group checks are in 02_larger_spatial_groups.csv. Neighbor residual correlations are diagnostic evidence of spatial dependence; larger-group uncertainty does not change the mean model or select passes. No expected cooling sign is used. Changes in effect magnitude under registration/composition remain sealed for review; precision stability alone does not certify effect stability.\n')
screen=json.loads((execution/'canopy_screen_summary.json').read_text());cat=json.loads((execution/'catalogue_audit_summary.json').read_text());topology=json.loads((execution/'domain_topology_audit.json').read_text());selection=json.loads((execution/'atlanta_selection_freeze.json').read_text())
screen_table=table(pd.DataFrame(screen),['city','valid_blocks','sampled_within_block_variance','max_block_information_share'],{'sampled_within_block_variance':'.5f','max_block_information_share':'.5f'})
sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.independent_foundation_audit import local_solar_hour
passmetadata=[]
for city in ['phoenix','atlanta']:
 c=json.loads((execution/f'{city}_execution_manifest.json').read_text())
 for orbit in c['orbits']:
  m=c['pass_metadata'][str(orbit)];passmetadata.append({'City':city,'Orbit':orbit,'UTC acquisition':m['acquisition_utc'],'Apparent solar hour':round(local_solar_hour(pd.Timestamp(m['acquisition_utc']).to_pydatetime(),c.get('centroid_longitude',-111.961187 if city=='phoenix' else -84.3365018)),3),'View p95 degrees':m['view_zenith_p95_deg']})
(OUT/'01_audit_and_sample_selection.md').write_text('''# Input audit and pilot selection

The nonthermal screen sampled 300 fixed 1km blocks per city, with seed 20260919, from blocks at least half inside the Census urban area. This area condition belongs to the comparative screening design, not the native-cell model eligibility rule. The screen used stable 2019–2025 Science TCC v2025-6 at its native 30m grid. It is not a substitute for the actual pass-specific native-cell support table.

'''+screen_table+'''

Atlanta was selected for its greater within-block variation and verified afternoon acquisitions. Its five passes are the first chronological 2023 June–September passes in the inherited inventory with verified L1B domain coverage at least 95% and p95 view zenith at most 25 degrees. This is a reproducible geometry-verified candidate frame; it is not claimed to enumerate every potentially usable pass. Selection was frozen before Atlanta thermal downloads. The second-city input scope is exactly five passes.

'''+table(pd.DataFrame(passmetadata),list(passmetadata[0]),{'View p95 degrees':'.3f'})+'''

Both pilot cities use Collection 2, including matching-granule wideband EmisWB, LST and QA layers. Every scene/layer must share the exact native 70m grid. The intended final 15-degree rule is not claimed for this inherited 25-degree precision sample. View and relative azimuth completeness remains unresolved for expanded-geometry claims; this is recorded rather than silently treated as complete.

The complete metadata audit reconciled every CMR page and hit count for Collections 2 and 3 in Phoenix, Atlanta and Charlotte. Reapplying the old June–September 2018–2025 filter exactly reproduced 2,600 Phoenix and 4,367 Atlanta granules; no old identifiers were missing. Mission-wide counts are larger because they include other months. Collection 3 does not yet provide consistent historical coverage for the intended study years. The two-city pilot uses Collection 2 throughout, and the expansion product decision remains open.

For spatial ownership, only whole native footprints inside their canonical 100km MGRS core and UTM longitude zone are retained. Cells crossing a seam are excluded; LST is never interpolated. Scene revisions are selected deterministically, same-tile scenes are merged with the frozen conservative cloud/water rule, and surviving duplicate native identities are prohibited. The accompanying count ledger separates raw scene observations, buffered/seam cells rejected, QA-valid unique cells and complete paired-model cells. Multiplying cell counts by 4,900 gives native footprint area; these categories should not all be interpreted as overlap removals.

Census polygons required make_valid topology repair in Phoenix and Atlanta. Equal-area changes were approximately −6,996 m² and −5,446 m² respectively, each less than 0.001% of the corresponding urban area. Original source geometries are preserved. Source geometry and projected geometry are repaired before operations; no simplifying buffer is applied.

Canopy is area-averaged only where the full contributing 30m support is valid and stable, within 1e-6 numerical coverage tolerance. Known-case tests verify area means, metadata scaling, fill values, scene choice, paired masks and seam ownership. Impervious 2021 validity is taken from its companion land-cover grid because the inherited file uses zero for both valid zero imperviousness and nodata. Annual NLCD 2024 and the inherited 3DEP snapshot are retained for matched context. Buildings use a 10m presence raster followed by area averaging, an approximation to exact vector fractions. Context dates differ from the 2023 thermal sample and must remain explicit in later sensitivity work.

A brief optional high-resolution canopy check found Phoenix’s published 2022 canopy summaries at census-tract level and an Atlanta 2018 canopy report. A downloadable, licensed ≤1m canopy layer with suitable dates and coverage was not verified in that brief check, so no validation statistics or replacement primary canopy product are claimed. Sources: [Phoenix canopy layer](https://maps.phoenix.gov/pub/rest/services/public/Shade_Study_Data_CMO_OHR/MapServer/1), [Atlanta canopy report](https://geospatial.gatech.edu/AtlantaUTC/2018FinalReport.pdf). This is not a pilot dependency.

The emitted-energy input follows the [ECOSTRESS Version 2 guide](https://lpdaac.usgs.gov/documents/1574/ECOL2_User_Guide_V2.pdf). Microsoft footprint release and varying imagery vintages are documented by the [producer](https://github.com/microsoft/USBuildingFootprints). Exact query records, export manifests, download checksums and selection freezes are under docs/v2/v6_2/execution and the pilot raw-input directory.
''')
info=primary[['city','pass_id','contributing_blocks','effective_information_blocks','maximum_block_information_share','top_five_block_information_share']]
with (OUT/'02_precision_and_support.md').open('a') as f:f.write('\nCanopy information is distributed as follows (shares are fractions):\n\n'+table(info,list(info.columns),{'effective_information_blocks':'.1f','maximum_block_information_share':'.5f','top_five_block_information_share':'.5f'})+'\n\nResidual cross-boundary neighbor correlations are provided in `02_residual_spatial_dependence.csv`; they motivate examining the larger-group standard errors.\n')
failed=pd.concat([allprecision,larger]);failed=failed[failed.bootstrap_failed>0]
with (OUT/'02_precision_and_support.md').open('a') as f:f.write('\nEleven of 90,000 requested spatial resamples were rank-deficient, all in Phoenix sensitivity fits. The estimator reports and omits those draws; every primary fit had 1,000 estimable draws. No pass was removed.\n\n'+table(failed,['city','pass_id','variant','bootstrap_requested','bootstrap_estimable','bootstrap_failed'])+'\n')
settings=json.loads((public/'scale_diagnostics_20260919/frozen_numeric_references.json').read_text());support=json.loads((public/'scale_diagnostics_20260919/time_support_status.json').read_text())
for name in ['SYNTHETIC_DATA_mixing_summary.csv','SYNTHETIC_DATA_time_comparison.csv','SYNTHETIC_DATA_transformation_artifact.png']:
 if not (synthetic/name).exists():raise ValueError('Synthetic diagnostic incomplete: '+name)
# Keep simulation files in their isolated root; meeting package links to them.
relative='../../tests/fixtures/synthetic_demo/mixing_20260919/'
mixing=pd.read_csv(synthetic/'SYNTHETIC_DATA_mixing_summary.csv');pure=mixing[mixing.scenario=='transformation_only']
conversion=f'''# Mixing test and standardized conversion

The frozen reference pair is f0 = {settings['f0']:.6f}, f1 = {settings['f1']:.6f}; Tref = {settings['reference_K']:.4f} K and epsilon_ref = {settings['reference_emissivity']:.6f}. Pair selection used canopy and block labels only: maximize the minimum number of supporting reference blocks across the ten passes, breaking ties toward smaller f0. These reference restrictions do not remove other blocks from the slope fit. Numerical anchors are equal-city means of equal-pass medians. Aggregate absolute-temperature access is disclosed separately from coefficient release.

For each city-pass, replace raw canopy by f0 and f1 in its frozen reference rows, subtract the original training block means, and retain all other covariates and valid block intercepts. Compute the weighted mean predicted M at each endpoint. With dM = mean Mhat(f1) − mean Mhat(f0), set Mref = epsilon_ref × sigma × Tref⁴ and calculate:

Delta T_equiv = [(Mref + dM)/(epsilon_ref × sigma)]^(1/4) − Tref.

Require positive anchored emission. Positive cooling is −Delta T_equiv. Average predictions before inverting; do not use a universal divisor. Reapply the transformation in each paired bootstrap draw with references fixed. Reference sensitivity uses Tref ±10 K and epsilon_ref ±0.01, capped at 0.999. Empirical prediction levels and contrasts stay sealed.

The primary time comparison is a prespecified city-specific linear pattern between 10:30 and 16:00 apparent local solar time. Both targets must lie inside each city’s observed range. An equal-city mean is calculated only for two supported city contrasts. Stage 1 uncertainty is propagated alongside independent-day resampling, with 1km and 8km spatial-uncertainty variants. Five passes per city support an exploratory feasibility comparison; they do not reconstruct a same-day diurnal curve. The secondary model adds solar elevation and day of year only when joint convex-hull support and residual degrees of freedom permit it.

'''+table(pd.DataFrame(support).reindex(columns=['city','variant','status','reason']).fillna(''),['city','variant','status','reason'])+f'''

The synthetic test uses 200 reproducibly sampled whole blocks per pass, constant component contrasts of 0, 2, 5 and 10 K, and 100 spatial bootstrap draws. Background temperatures and equal-component emissivities in the no-noise scenario are observed block medians, which remove the empirical canopy-temperature association. A within-block permutation sensitivity retains observed temperature distributions without republishing a sealed empirical regression as a zero-control simulation. Additional scenarios add correlated error, unequal component emissivity, narrower canopy support and ±10 K background shifts. Exact component temperatures are assumptions, not retrieved canopy temperatures.

The matched zero-contrast control is subtracted to isolate transformation departures from the known linear-temperature benchmark, 0.10 × component contrast. A fixed component temperature difference need not yield a fixed energy difference; the standardized energy-space variation is therefore not automatically a spurious effect.

'''+table(pure,['constant_contrast_K','T_cross_pass_range_K_per_10pp','T_city_mean_difference_atlanta_minus_phoenix','max_abs_transformation_departure_K_per_10pp'],{c:'.6f' for c in ['T_cross_pass_range_K_per_10pp','T_city_mean_difference_atlanta_minus_phoenix','max_abs_transformation_departure_K_per_10pp']})+f'''\n\n![SYNTHETIC DATA transformation departures]({relative}SYNTHETIC_DATA_transformation_artifact.png)

[All synthetic scenarios]({relative}SYNTHETIC_DATA_mixing_summary.csv) and [synthetic time comparisons]({relative}SYNTHETIC_DATA_time_comparison.csv). These are simulated diagnostics and do not disclose the empirical cooling effect or settle the headline-scale decision.
'''
(OUT/'03_mixing_and_standardization.md').write_text(conversion)
t=pd.read_csv(synthetic/'SYNTHETIC_DATA_time_comparison.csv');t=t[(t.scenario=='transformation_only')&(t.constant_contrast_K>0)]
with (OUT/'03_mixing_and_standardization.md').open('a') as f:f.write('\nSimulated 10:30-to-16:00 time contrasts under constant component contrasts (K per 10 percentage points):\n\n'+table(t,['city','constant_contrast_K','artificial_time_contrast_T','time_contrast_M_equivalent'],{'artificial_time_contrast_T':'.6f','time_contrast_M_equivalent':'.6f'})+'\n\nEnergy-equivalent time variation includes the physical change in emitted energy with baseline temperature; it is not all temperature-transformation artifact.\n')
(OUT/'04_decisions_for_Reza.md').write_text('''# Decisions for Reza after precision review

The limited pilot implements the pooled city-pass estimator and paired measurement-space test. Review the full ten-pass precision table, information concentration, native-cell audit, registration/common-cell checks and larger spatial groups. A low standard error establishes measurement feasibility; it does not establish the time pattern, a causal effect or equivalence.

1. Set the numerical scale-agreement tolerance in K per 10 percentage points before any empirical contrast is displayed. The approximately 0.10 K SE benchmark addresses precision and is not that tolerance. No 0.05 value has been adopted.
2. Record whether to release the prespecified empirical pass coefficients and 10:30-versus-16:00 contrasts after precision review. The current user instruction keeps them sealed. Code has computed supported comparisons internally; the package displays no signs, effect magnitudes or empirical interval endpoints.
3. Review the frozen 25-degree precision exception, missing azimuth completeness, sparse temporal sampling and any secondary geometry/season support failure. A non-estimable secondary model is reported explicitly while retaining the total-time interpretation.
4. Before expansion, resolve the ECOSTRESS collection plan against the catalogue’s incomplete Collection 3 historical coverage and design independent-pass power using the pilot uncertainty and nonthermal time coverage. No arbitrary eight-pass or four-of-five rule is imposed.

The scale ruling remains pending. Agreement requires the same nonzero direction and an absolute paired discrepancy strictly below the frozen tolerance. Material discrepancy or reversal makes emitted energy the primary physical analysis and temperature-space results scale-dependent. At zero or with weak/support-limited contrasts, report uncertainty rather than a robustness pass.

Full-city archives, additional-city thermal downloads, eight-class unmixing and the deferred HLS/VPD hypothesis remain outside this run. VPD remains descriptive, and the global paper remains an observational climatic association in the literature review. The primary annual multi-city Science TCC product has not been replaced.
''')
manifest=[]
for p in sorted(OUT.iterdir()):
 if p.is_file() and p.name!='checksums.sha256':manifest.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name)
(OUT/'checksums.sha256').write_text('\n'.join(manifest)+'\n');print('MEETING_PACKAGE_READY',str(OUT))
