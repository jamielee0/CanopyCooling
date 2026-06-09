#!/usr/bin/env python3
"""Authentication smoke test for the four Canopy data services.

Attempts one minimal authenticated call against each service and prints
PASS / FAIL per service. No secrets are hard-coded — every credential is read
from the standard file or environment variable that each library expects:

  * NASA Earthdata     earthaccess  -> ~/.netrc  or EARTHDATA_USERNAME/PASSWORD
  * Google Earth Engine ee          -> ~/.config/earthengine/credentials
                                        + EARTHENGINE_PROJECT / GOOGLE_CLOUD_PROJECT
  * Copernicus CDS     cdsapi       -> ~/.cdsapirc  or CDSAPI_URL/CDSAPI_KEY
  * US Census          REST API     -> CENSUS_API_KEY (optional)

Run after you have completed each service's login yourself:
    python src/check_auth.py

Exit code is 0 only if all four services PASS, otherwise 1.
"""

from __future__ import annotations

import os
import sys

# Make the sibling config module importable whether run from repo root or src/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def _ok(name: str, detail: str = "") -> tuple[str, bool, str]:
    return (name, True, detail)


def _fail(name: str, detail: str) -> tuple[str, bool, str]:
    return (name, False, detail)


def check_earthdata() -> tuple[str, bool, str]:
    """Authenticate to NASA Earthdata via earthaccess and confirm a token."""
    name = "Earthdata (earthaccess)"
    try:
        import earthaccess

        # login() reads ~/.netrc, then EARTHDATA_USERNAME/PASSWORD env vars.
        auth = earthaccess.login()
        if getattr(auth, "authenticated", False):
            return _ok(name, "token acquired")
        return _fail(name, "login() returned but not authenticated")
    except Exception as exc:  # noqa: BLE001 - report any failure verbatim
        return _fail(name, f"{type(exc).__name__}: {exc}")


def check_earthengine() -> tuple[str, bool, str]:
    """Initialise Earth Engine and run a trivial server-side computation."""
    name = "Earth Engine (ee.Initialize)"
    try:
        import ee

        project = os.environ.get("EARTHENGINE_PROJECT") or os.environ.get(
            "GOOGLE_CLOUD_PROJECT"
        )
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()  # uses default project from stored credentials
        # Trivial authenticated round-trip to the EE backend.
        value = ee.Number(1).add(1).getInfo()
        if value == 2:
            return _ok(name, f"compute OK (project={project or 'default'})")
        return _fail(name, f"unexpected compute result: {value!r}")
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


def check_cds() -> tuple[str, bool, str]:
    """Construct a cdsapi client (reads ~/.cdsapirc or CDSAPI_URL/CDSAPI_KEY)."""
    name = "CDS (cdsapi)"
    try:
        import cdsapi

        # Client() validates URL+key configuration and contacts the API.
        client = cdsapi.Client(quiet=True, wait_until_complete=False)
        # Best-effort authenticated probe; older clients lack .status().
        status = getattr(client, "status", None)
        if callable(status):
            status()
        return _ok(name, "client initialised")
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


def check_census() -> tuple[str, bool, str]:
    """Make one trivial Census API request, using CENSUS_API_KEY if present."""
    name = "Census (api.census.gov)"
    try:
        import requests

        key = os.environ.get("CENSUS_API_KEY")
        # Smallest meaningful query: one variable for one state.
        url = "https://api.census.gov/data/2020/dec/pl"
        params = {"get": "NAME", "for": "state:01"}
        if key:
            params["key"] = key
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) >= 2:
            keyed = "with key" if key else "no key (anonymous)"
            return _ok(name, f"HTTP 200, {keyed}")
        return _fail(name, f"unexpected payload: {data!r:.80}")
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


def main() -> int:
    checks = (
        check_earthdata,
        check_earthengine,
        check_cds,
        check_census,
    )
    results = [fn() for fn in checks]

    print("\nCanopy authentication check")
    print("=" * 60)
    all_pass = True
    for service, passed, detail in results:
        tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        all_pass &= passed
        line = f"{tag}  {service}"
        if detail:
            line += f"  —  {detail}"
        print(line)
    print("=" * 60)
    print("All services PASS." if all_pass else "One or more services FAILED.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
