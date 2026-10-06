URBAN TREE COOLING — CODE
Jamie Lee  ·  6 August 2026

123 Python files, about 72,000 lines. This is the whole thing, minus data,
figures and credentials. The layout is the real repository layout, so the code
runs as-is if you set up the environment.


IF YOU ONLY LOOK AT THREE THINGS

  configs/v2_cities.toml
        Every threshold in the study, in about 40 lines. The near-nadir cutoff,
        the daytime window, the minimum corner support, the domain rules. If you
        disagree with a number, it is in here rather than buried in code.

  src/urban_cooling_v2/step02_l1b_geometry.py, line 1389
        The eight lines that take 911 candidate passes down to 219. This is the
        single most consequential filter in the project.

  src/urban_cooling_v2/step02_catalog.py, line 535
        join_acquisition_time_conditions. This is where I now think there is a
        problem — see the note at the bottom of this file.


LAYOUT

  configs/               All frozen thresholds. v2_cities.toml is the main one.
  environment.yml        Conda environment (Python 3.11).
  config.py              v1 paths and frozen Phoenix geometry. No secrets.
  README.md              The v1 project readme.

  src/urban_cooling_v2/  The v2 package, 29 modules. The guide implementation.
  src/run_v2_*.py        Runners. These are what actually execute a step.
  src/test_v2_*.py       34 test files for v2.

  src/section*.py        The v1 Phoenix pipeline, one module per section.
  src/test_section*.py   v1 tests.
  src/run_all.py         The v1 driver, 17 steps in dependency order.

  src/build_prof_spec_support_grid.py
  src/build_window_length_support_check.py
                         The two figures in the review packet. Both assert that
                         they reproduce the published tables and fail if not.

  docs/                  Design rationale (v1) and the v2 governance documents,
                         including the append-only decision log.


READING ORDER FOR THE V2 PIPELINE

  step02_catalog.py        Catalogue, local solar time, the attrition stages,
                           and the 3x3 condition cells. Start here — the tuple
                           ATTRITION_STAGES at line 61 is the whole funnel.
  step02_enrich.py         Scene metadata: geolocation quality, obstruction,
                           retrieval band mode.
  step02_l1b_geometry.py   Near-nadir screening on cloud-independent geometry.
                           Most of the file is network and provenance handling;
                           the science is the coverage/angle test at line 1389.
  step02_cloud_exhaustive.py
                           Official cloud fraction per pass. This is what turns
                           a pass into a fractional "pass-equivalent".
  step02_hrrr_fetch.py     Weather interpolated to the exact overpass second.
  step03_time_of_day_power.py
                           The simulation that produced the 0.110 power result.


RUNNING THE TESTS

  conda env create -f environment.yml
  conda activate canopy
  python src/test_v2_step02_catalog.py

  Each test file is standalone and uses small synthetic arrays. No network, no
  credentials, no data downloads. 139 v2 tests and 133 v1 tests pass.


CREDENTIALS

  None are included, and none are in the code. Authentication is read at runtime
  from ~/.netrc or environment variables — see src/check_auth.py. You will need
  your own Earthdata login to re-run anything that touches the archive.

  Two files contain lists of words like "token" and "password": these are
  redaction lists that strip credentials out of URLs before they are written
  into evidence logs. See _SENSITIVE_QUERY_NAMES in step02_enrich_fetch.py
  line 57.


ONE THING I WANT TO FLAG MYSELF

  In step02_catalog.py, join_acquisition_time_conditions ranks the vapour
  pressure deficit at the moment of each overpass against the frozen Step-1
  reference distribution. The intent was to stop "high demand" being defined
  relative to only the days the satellite happened to see, which I still think
  is right. But the Step-1 reference is built from gridMET daily MEAN values,
  so an instantaneous afternoon reading is being ranked against a distribution
  of daily averages. Afternoons are much drier than day averages, so almost
  everything ranks high: my demand terciles come out 32 / 32 / 155 instead of
  roughly even.

  Recomputing with a consistent comparison, the terciles balance to 70 / 78 / 71
  and both diagnostic corners fail the minimum support rule, rather than one
  passing and one failing. So the Step-2 STOP holds either way, and if anything
  it holds more clearly. But the demand percentile as published does not mean
  what its label says, and I would like to fix it properly by building the
  reference from a climatology at comparable times of day.

  I found this while testing whether my filters were too strict. I have not
  changed any published number on the strength of it.
