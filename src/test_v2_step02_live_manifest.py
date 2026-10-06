#!/usr/bin/env python3
"""Network-free checks for cached Task-1 CMR query replay."""

from pathlib import Path
import tempfile

from urban_cooling_v2.step02_live_manifest import cached_cmr_query


def test_cached_query_runs_once_and_rejects_changed_query() -> None:
    calls = []

    def fake_search(**kwargs):
        calls.append(kwargs)
        return [{"umm": {"GranuleUR": "one"}}]

    query = {
        "short_name": "ECO_L2T_LSTE",
        "version": "002",
        "temporal": ("2025-06-01", "2025-09-30"),
        "count": -1,
    }
    with tempfile.TemporaryDirectory(prefix="cmr-cache-") as temporary:
        path = Path(temporary) / "query.json"
        first = cached_cmr_query(path, search_data=fake_search, query=query)
        replay = cached_cmr_query(path, search_data=fake_search, query=query)
        assert first == replay
        assert len(calls) == 1
        try:
            cached_cmr_query(
                path,
                search_data=fake_search,
                query={**query, "version": "003"},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("changed cached query must be rejected")


if __name__ == "__main__":
    test_cached_query_runs_once_and_rejects_changed_query()
    print("PASS test_cached_query_runs_once_and_rejects_changed_query")
