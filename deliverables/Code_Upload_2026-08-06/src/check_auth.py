#!/usr/bin/env python3
"""Section 0 / check_auth — smoke-test authentication for the four Canopy data services.

Inputs : credentials only (no data); read from each library's standard location:
         ~/.netrc | ~/.config/earthengine/credentials | ~/.cdsapirc, plus env vars,
         plus an optional gitignored project-root .env (real env always wins).
Outputs: PASS/FAIL per service to stdout; exit 0 only if all four PASS, else 1.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 0):
  - No secrets in code: credentials read from standard files/env per library.
  - One minimal authenticated call per service (Earthdata, Earth Engine, CDS, Census).
Run: python src/check_auth.py
"""

from __future__ import annotations

import os
import sys

# Importable whether run from repo root or src/.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def load_dotenv(path: str) -> bool:
    """Minimal .env loader (no external deps); does not overwrite real env vars."""
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            os.environ.setdefault(key, val)
    return True


def _ok(name: str, detail: str = "") -> tuple[str, bool, str]:
    return (name, True, detail)


def _fail(name: str, detail: str) -> tuple[str, bool, str]:
    return (name, False, detail)


def check_earthdata() -> tuple[str, bool, str]:
    """Authenticate to NASA Earthdata via earthaccess and confirm a token."""
    name = "Earthdata (earthaccess)"
    try:
        import earthaccess

        # login() reads EARTHDATA_USERNAME/PASSWORD env vars, then ~/.netrc.
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

        client = cdsapi.Client(quiet=True, wait_until_complete=False)
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


def _print_sources() -> None:
    """Report which credential sources were detected (no secret values shown)."""
    home = os.path.expanduser("~")
    netrc = os.environ.get("NETRC", os.path.join(home, ".netrc"))
    checks = [
        ("EARTHDATA_USERNAME/PASSWORD env",
         bool(os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"))),
        ("~/.netrc", os.path.exists(netrc)),
        ("EARTHENGINE_PROJECT", bool(os.environ.get("EARTHENGINE_PROJECT")
                                     or os.environ.get("GOOGLE_CLOUD_PROJECT"))),
        ("~/.config/earthengine/credentials",
         os.path.exists(os.path.join(home, ".config", "earthengine", "credentials"))),
        ("~/.cdsapirc", os.path.exists(os.path.join(home, ".cdsapirc"))),
        ("CDSAPI_URL/CDSAPI_KEY env",
         bool(os.environ.get("CDSAPI_URL") and os.environ.get("CDSAPI_KEY"))),
        ("CENSUS_API_KEY", bool(os.environ.get("CENSUS_API_KEY"))),
    ]
    print("Credential sources detected:")
    for label, found in checks:
        mark = f"{GREEN}found{RESET}" if found else f"{YELLOW}missing{RESET}"
        print(f"  [{mark}] {label}")


def main() -> int:
    dotenv_path = os.path.join(_REPO_ROOT, ".env")
    loaded = load_dotenv(dotenv_path)
    print(f"\n.env: {'loaded ' + dotenv_path if loaded else 'not found (using real env / cred files)'}")
    _print_sources()

    checks = (check_earthdata, check_earthengine, check_cds, check_census)
    results = [fn() for fn in checks]

    print("\nCanopy authentication check")
    print("=" * 60)
    all_pass = True
    for service, passed, detail in results:
        tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        all_pass &= passed
        line = f"{tag}  {service}"
        if detail:
            line += f"  -  {detail}"
        print(line)
    print("=" * 60)
    print("All services PASS." if all_pass else "One or more services FAILED.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
