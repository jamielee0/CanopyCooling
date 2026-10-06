# v6.2 implementation status

The analysis code in this directory predates the 19 September documentation amendment. It is preserved for reproducibility and has not yet been changed to implement the pooled city-pass estimator, paired emitted-energy analysis or new pass-level support rules.

Before running the amended pilot, follow `../docs/v2/v6_2/implementation_plan_v6_2.md` and the controlling protocol. Do not treat a successful old block-pass test suite as acceptance of the new estimator. Preserve old result packages, but update the new runner and meaningful tests against the amended design.

The `data` symlink currently names the earlier location of the data directory. Verify the relocated path documented in the root README before future execution. No data or code was changed by this documentation update.
