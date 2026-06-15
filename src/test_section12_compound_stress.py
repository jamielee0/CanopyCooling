#!/usr/bin/env python3
"""Self-test for the Section 12 Compound Stress Index pipeline (pure-logic).

Mirrors test_section2-11_*: the geo stack (rioxarray, xarray, rasterio) is stubbed
so the module imports with only numpy + pandas, then the algorithmically risky PURE
logic is exercised on tiny SYNTHETIC arrays (NO network, NO full Zarr):

  * demand stress = positive part of the VPD z-score, max(vpd_z, 0)        (step 62)
  * supply stress = positive part of the NEGATED water-supply z-score,
    max(-ndmi_z, 0) -- i.e. a NEGATIVE NDMI z becomes a POSITIVE stress     (step 63)
  * the baseline EQUAL-weight CSI = 0.5*demand + 0.5*supply, AND the
    parameterised compute_csi(demand, supply, w_demand, w_supply) with other
    weights (the step-66 unequal-weight sensitivity HOOK)                   (step 64)
  * CSI >= 0 everywhere (it is built from non-negative parts with non-negative
    weights), and NaN is preserved (missing pixels stay missing)            (step 65)
  * the protocol PITFALL guard: the supply stress is built from the NDMI *z-score*,
    NOT raw NDMI -- proven by showing raw NDMI (mean ~ -0.07) and its z-score give
    DIFFERENT supply stresses, and that compute_csi on raw NDMI would be dominated
    by the larger-range term (so z-scores are required)
  * the copula_weights() STUB raises NotImplementedError (step-66 placeholder, not run)
  * the baseline weights in config.py are 0.5 / 0.5

The Zarr load/assembly/write, CRS round-trip, the _assert_inputs_are_zscores geo
check and matplotlib glue are standard library usage exercised by the real CLI in
the canopy environment (and by the end-to-end run), not re-implemented here.

Runs with just numpy + pandas:  python src/test_section12_compound_stress.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module (and section11) import with
    only numpy + pandas (section12 imports section11_anomalies at top level)."""
    for name in ("rioxarray", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object            # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object           # type: ignore[attr-defined]
        sys.modules["xarray"].open_zarr = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["xarray"].open_dataset = lambda *a, **k: None  # type: ignore[attr-defined]
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    if "rasterio.enums" not in sys.modules:
        enums = types.ModuleType("rasterio.enums")

        class _Resampling:
            bilinear = "bilinear"
            nearest = "nearest"
            average = "average"

        enums.Resampling = _Resampling
        sys.modules["rasterio.enums"] = enums
        sys.modules["rasterio"].enums = enums              # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec12 = importlib.import_module("section12_compound_stress")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# --------------------------------------------------------------------------- #
# 1. demand stress = positive part of vpd_z (step 62).
# --------------------------------------------------------------------------- #
def test_demand_stress_positive_part() -> None:
    print("\n[demand stress = max(vpd_z, 0) (step 62)]")
    vpd_z = np.array([-2.0, -0.5, 0.0, 0.5, 3.0])
    d = sec12.demand_stress(vpd_z)
    check(d.tolist() == [0.0, 0.0, 0.0, 0.5, 3.0],
          "demand keeps positive z, zeroes negative/zero z (only above-normal VPD is stressful)")
    check(np.all(d >= 0.0), "demand stress is >= 0 everywhere")
    # NaN must be preserved (a missing pixel stays missing, not 0).
    dn = sec12.demand_stress(np.array([np.nan, 1.0]))
    check(np.isnan(dn[0]) and dn[1] == 1.0, "NaN VPD z is preserved (not turned into 0)")


# --------------------------------------------------------------------------- #
# 2. supply stress = positive part of the NEGATED ndmi_z (step 63).
# --------------------------------------------------------------------------- #
def test_supply_stress_negated_positive_part() -> None:
    print("\n[supply stress = max(-ndmi_z, 0): low water (negative z) -> positive stress (step 63)]")
    ndmi_z = np.array([-2.0, -0.5, 0.0, 0.5, 3.0])
    s = sec12.supply_stress(ndmi_z)
    # negated: -(-2,-0.5,0,0.5,3) = (2,0.5,0,-0.5,-3) then clamp at 0 -> (2,0.5,0,0,0)
    check(s.tolist() == [2.0, 0.5, 0.0, 0.0, 0.0],
          "a BELOW-normal NDMI (negative z) becomes a POSITIVE supply stress; above-normal -> 0")
    check(np.all(s >= 0.0), "supply stress is >= 0 everywhere")
    dn = sec12.supply_stress(np.array([np.nan, -1.0]))
    check(np.isnan(dn[0]) and dn[1] == 1.0, "NaN NDMI z is preserved")
    # the sign convention is the crux: the MOST stressful pixel has the LOWEST NDMI z.
    check(s[0] == np.max(s), "the lowest NDMI z (-2) yields the largest supply stress")


# --------------------------------------------------------------------------- #
# 3. baseline equal-weight CSI + the parameterised weight hook (step 64 / 66).
# --------------------------------------------------------------------------- #
def test_compute_csi_equal_weights() -> None:
    print("\n[baseline CSI = 0.5*demand + 0.5*supply (step 64)]")
    demand = np.array([0.0, 1.0, 2.0, 4.0])
    supply = np.array([1.0, 0.0, 2.0, 0.0])
    csi = sec12.compute_csi(demand, supply, 0.5, 0.5)
    check(np.allclose(csi, [0.5, 0.5, 2.0, 2.0]), "CSI = 0.5*demand + 0.5*supply elementwise")
    # using the config defaults (which must be 0.5/0.5) gives the same answer
    csi_def = sec12.compute_csi(demand, supply)
    check(np.allclose(csi_def, csi), "compute_csi defaults to the config equal weights")
    check(np.all(csi >= 0.0), "equal-weight CSI is >= 0 when both parts are >= 0")


def test_compute_csi_parameterised_weights() -> None:
    print("\n[parameterised compute_csi -- the step-66 unequal-weight HOOK]")
    demand = np.array([2.0, 0.0])
    supply = np.array([0.0, 2.0])
    # all-demand weighting
    csi_d = sec12.compute_csi(demand, supply, 1.0, 0.0)
    check(np.allclose(csi_d, [2.0, 0.0]), "w_demand=1, w_supply=0 -> CSI == demand")
    # all-supply weighting
    csi_s = sec12.compute_csi(demand, supply, 0.0, 1.0)
    check(np.allclose(csi_s, [0.0, 2.0]), "w_demand=0, w_supply=1 -> CSI == supply")
    # an arbitrary unequal weighting is a trivial re-call (the whole point of the hook)
    csi_u = sec12.compute_csi(demand, supply, 0.7, 0.3)
    check(np.allclose(csi_u, [1.4, 0.6]), "unequal weights (0.7/0.3) are a trivial re-call")


def test_csi_nonnegative_and_nan_preserved() -> None:
    print("\n[CSI >= 0 everywhere; NaN preserved (step 65)]")
    rng = np.random.default_rng(1)
    vpd_z = rng.normal(0, 1, size=2000)
    ndmi_z = rng.normal(0, 1, size=2000)
    vpd_z[5] = np.nan
    d = sec12.demand_stress(vpd_z)
    s = sec12.supply_stress(ndmi_z)
    csi = sec12.compute_csi(d, s, 0.5, 0.5)
    fin = np.isfinite(csi)
    check(bool(np.all(csi[fin] >= 0.0)), "CSI >= 0 over all finite cells (positive parts)")
    check(np.isnan(csi[5]), "a NaN VPD z propagates to a NaN CSI (missing stays missing)")


# --------------------------------------------------------------------------- #
# 4. PITFALL guard: supply built from the z-score, NOT raw NDMI (step 63 + pitfall).
# --------------------------------------------------------------------------- #
def test_supply_uses_zscore_not_raw_ndmi() -> None:
    print("\n[PITFALL guard: supply stress uses the NDMI Z-SCORE, not raw NDMI]")
    # A realistic raw NDMI field: mean ~ -0.07, small spread (~0.09) -- the Section 4
    # composite scale. Its z-score is the Section 11 spatial standardization.
    rng = np.random.default_rng(2)
    raw_ndmi = rng.normal(loc=-0.07, scale=0.09, size=5000)
    mu, sigma = float(np.mean(raw_ndmi)), float(np.std(raw_ndmi))
    ndmi_z = (raw_ndmi - mu) / sigma

    supply_from_z = sec12.supply_stress(ndmi_z)
    supply_from_raw = sec12.supply_stress(raw_ndmi)   # the WRONG input (the pitfall)
    # The two are on completely different scales -> NOT interchangeable.
    check(not np.allclose(supply_from_z, supply_from_raw, atol=1e-3),
          "supply from the z-score differs from supply from raw NDMI (different inputs)")
    # The z-score supply is on the z scale (~order 1); the raw-NDMI supply is ~0.07.
    check(np.max(supply_from_z) > 1.0, "z-score supply reaches order-1 magnitudes (z units)")
    check(np.max(supply_from_raw) < 0.5,
          "raw-NDMI supply is tiny (~0.07 scale) -- it is NOT on the demand z scale")

    # The pitfall consequence: equal-weight CSI built on the z scale is BALANCED, but
    # built with a raw-NDMI supply against a z-score demand it is DEMAND-DOMINATED
    # (the supply term is ~10x smaller), which is exactly what the protocol warns about.
    vpd_z = rng.normal(0, 1, size=5000)
    demand = sec12.demand_stress(vpd_z)            # on the z scale (same as the correct supply)
    csi_correct = sec12.compute_csi(demand, supply_from_z, 0.5, 0.5)
    csi_pitfall = sec12.compute_csi(demand, supply_from_raw, 0.5, 0.5)
    # share of the (equal-weighted) CSI carried by the SUPPLY term.
    supply_share_correct = np.mean(0.5 * supply_from_z) / np.mean(csi_correct)
    supply_share_pitfall = np.mean(0.5 * supply_from_raw) / np.mean(csi_pitfall)
    # With z-scores both stresses are on the same scale, so the supply term carries a
    # BALANCED ~half of the CSI; with raw NDMI (a ~10x smaller range) the supply term is
    # a much smaller minority and the CSI is DEMAND-dominated -- exactly the pitfall.
    check(supply_share_correct > 0.40,
          "with z-scores the supply term carries a balanced ~half of the equal-weight CSI")
    check(supply_share_pitfall < 0.25,
          "with raw NDMI the supply term is a small minority -> the CSI is demand-dominated (the pitfall)")
    check(supply_share_correct > 2.0 * supply_share_pitfall,
          "z-score supply carries materially more of the CSI than raw-NDMI supply -> z-scores are required")
    check(sec12.SUPPLY_Z_VAR == "ndmi_z" and sec12.DEMAND_Z_VAR == "vpd_z",
          "the module reads the Z-SCORE variables (vpd_z / ndmi_z), not raw VPD/NDMI")


# --------------------------------------------------------------------------- #
# 5. step-66 copula STUB is a placeholder (NotImplementedError), not executed.
# --------------------------------------------------------------------------- #
def test_copula_weights_is_unrun_stub() -> None:
    print("\n[copula_weights() is a step-66 STUB -- raises NotImplementedError, never run]")
    raised = False
    try:
        sec12.copula_weights()
    except NotImplementedError:
        raised = True
    check(raised, "copula_weights() raises NotImplementedError (clearly a placeholder)")
    # also tolerant of being called with args (a future caller's signature)
    raised2 = False
    try:
        sec12.copula_weights(np.array([1.0]), np.array([1.0]))
    except NotImplementedError:
        raised2 = True
    check(raised2, "copula_weights(*args) still raises (the stub ignores any args)")


# --------------------------------------------------------------------------- #
# 6. heatwave enrichment is reused from Section 11 (single source of truth).
# --------------------------------------------------------------------------- #
def test_heatwave_helpers_delegate_to_section11() -> None:
    print("\n[heatwave window + enrichment reuse Section 11 (single source of truth)]")
    check(sec12.in_heatwave("2023-07-20"), "mid-July 2023 is in the heatwave window")
    check(not sec12.in_heatwave("2023-09-01"), "September 2023 is after the window")
    check(sec12.HEATWAVE_2023[0] == pd.Timestamp("2023-06-30")
          and sec12.HEATWAVE_2023[1] == pd.Timestamp("2023-07-30"),
          "the 2023 peak-heat window matches Section 11 (Jun 30 .. Jul 30)")
    # enrichment: in-window overpasses with the highest CSI -> >1 enrichment
    times = pd.to_datetime(["2023-07-10", "2023-07-20", "2023-07-25",
                            "2023-06-05", "2023-08-15", "2023-09-10"])
    scores = np.array([3.0, 2.9, 2.8, 0.1, 0.2, 0.0])
    enr = sec12.heatwave_enrichment(times, scores, top_k=3)
    check(abs(enr["top_frac"] - 1.0) < 1e-9 and enr["enrichment"] > 1.0,
          "the 2023-window overpasses dominate the top scores -> enrichment > 1")


# --------------------------------------------------------------------------- #
# 7. config baseline weights + module constants.
# --------------------------------------------------------------------------- #
def test_module_constants_and_weights() -> None:
    print("\n[config baseline weights + module source constants]")
    import config
    check(abs(config.WEIGHT_DEMAND - 0.5) < 1e-12, "config.WEIGHT_DEMAND == 0.5 (baseline)")
    check(abs(config.WEIGHT_SUPPLY - 0.5) < 1e-12, "config.WEIGHT_SUPPLY == 0.5 (baseline)")
    check(abs((config.WEIGHT_DEMAND + config.WEIGHT_SUPPLY) - 1.0) < 1e-12,
          "the baseline weights sum to 1 (equal split)")
    check(sec12.DEMAND_Z_VAR == "vpd_z", "demand is built from the VPD z-score variable")
    check(sec12.SUPPLY_Z_VAR == "ndmi_z", "supply is built from the NDMI z-score variable")
    check(sec12.ZSCORE_ZARR == "section11_zscores_70m.zarr",
          "the only input is the Section 11 z-score store")


# --------------------------------------------------------------------------- #
# Direct runner (parity with the sibling test modules).
# --------------------------------------------------------------------------- #
def main() -> int:
    tests = [
        test_demand_stress_positive_part,
        test_supply_stress_negated_positive_part,
        test_compute_csi_equal_weights,
        test_compute_csi_parameterised_weights,
        test_csi_nonnegative_and_nan_preserved,
        test_supply_uses_zscore_not_raw_ndmi,
        test_copula_weights_is_unrun_stub,
        test_heatwave_helpers_delegate_to_section11,
        test_module_constants_and_weights,
    ]
    print("=" * 64)
    print("Section 12 pure-logic self-test")
    print("=" * 64)
    for t in tests:
        t()
    print("\n" + "=" * 64)
    if _FAILURES:
        print(f"{len(_FAILURES)} CHECK(S) FAILED:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
