# Literature: what the papers support, and what we propose

These are proposed refinements within v6.2, not claims that the papers prescribe our exact estimator, sample size, time windows, weights, spatial block size or city list.

1. **Observation time, dates and weather.** Vo, T. T., & Hu, L. (2021), *Diurnal evolution of urban tree temperature at a city scale*, Scientific Reports 11, 10491. Their ECOSTRESS sequence uses observations on different days and explicitly acknowledges daily weather differences. Their component-temperature unmixing is distinct from our mixed-pixel canopy association. [Article and methods](https://www.nature.com/articles/s41598-021-89972-0).

   **Proposed application:** audit month-by-time support and report a within-year/month comparison where available. The June/August 2023 balancing weights are our design response, not the published method. The missing July/September morning acquisitions come from our catalogue audit. A window mean is not the exact 10:30–16:00 prediction target.

2. **Canopy dependence and reference conditions.** Zhao, J., Zhao, X., Wu, D., Meili, N., & Fatichi, S. (2023), *Satellite-based evidence highlights a considerable increase of urban tree cooling benefits from 2000 to 2015*, Global Change Biology 29, 3085–3097. The study compares cooling efficiencies at reference canopy and air-temperature conditions and finds canopy-dependent cooling efficiency. [Article](https://onlinelibrary.wiley.com/doi/10.1111/gcb.16667).

   **Proposed application:** retain the pooled linear baseline but test a modest nonlinear canopy response and calculate finite contrasts on common supported canopy/context settings. Our synthetic common-curve demonstration shows a possible range artifact; it does not estimate the actual Phoenix/Atlanta bias. The paper's VPD result remains an observational climatic association. Our own support diagnostics determine VPD's descriptive-only role.

3. **Regression of estimated pass slopes.** Lewis, J. B., & Linzer, D. A. (2005), *Estimating Regression Models in Which the Dependent Variable Is Based on Estimates*, Political Analysis 13, 345–364. The paper treats unequal sampling uncertainty in estimated dependent variables and explains why naive weighted least squares is not automatically appropriate. [Article](https://doi.org/10.1093/pan/mpi026).

   **Proposed application:** separate first-stage sampling uncertainty from residual between-day variation, and calibrate a temporal/hierarchical model against a simpler day-cluster benchmark. The double-noise bootstrap issue is a finding from our code audit/simulation, not a result reported in this article.

4. **Validation with dependent observations.** Roberts, D. R., et al. (2017), *Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure*, Ecography 40, 913–929. Random folds can understate predictive error for structured data; the appropriate blocking reflects the prediction task and can introduce extrapolation. [Article](https://doi.org/10.1111/ecog.02881).

   **Proposed application:** validate flexible models by holding out whole days or cities as appropriate. This does not establish that 8 km bootstrap blocks are independent or directly justify a particular confidence-interval procedure. Our spatial dependence diagnostics independently motivate the spatial sensitivity checks.

## Data-derived proposals

The nineteen-city shortlist, the observed cloud-support gap used to prioritize a separate exploratory acquisition batch, the absence of July/September 2023 morning passes, and the numerical precision results are project findings. They are not attributed to these papers. More passes and more complex models are not automatically better: supported comparisons and calibrated uncertainty remain the criteria for expansion.
