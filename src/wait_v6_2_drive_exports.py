#!/usr/bin/env python3
"""Wait for the v6.2 Earth Engine exports and fail closed on job errors."""

from __future__ import annotations

import collections
import json
import time

import ee


EE_PROJECT = "tree-497018"
PREFIXES = ("utc_v6_2_science_tcc_", "utc_v6_2_usgs_3dep_10m_")
EXPECTED = 16
RANK = {
    "COMPLETED": 5,
    "RUNNING": 4,
    "READY": 3,
    "CANCEL_REQUESTED": 2,
    "FAILED": 1,
    "CANCELLED": 0,
}


def preferred_jobs() -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for task in ee.data.getTaskList():
        key = task.get("description", "")
        if key.startswith(PREFIXES):
            grouped.setdefault(key, []).append(task)
    return [
        max(group, key=lambda task: RANK.get(task.get("state", ""), -1))
        for group in grouped.values()
    ]


def main() -> None:
    ee.Initialize(project=EE_PROJECT)
    last_summary = None
    while True:
        jobs = preferred_jobs()
        states = dict(collections.Counter(job.get("state") for job in jobs))
        summary = {"unique_jobs": len(jobs), "states": states}
        if summary != last_summary:
            print(json.dumps(summary), flush=True)
            last_summary = summary

        failed = [
            job
            for job in jobs
            if job.get("state") in {"FAILED", "CANCELLED", "CANCEL_REQUESTED"}
        ]
        if failed:
            print(
                json.dumps(
                    {
                        "status": "FAILED",
                        "jobs": [
                            {
                                "description": job.get("description"),
                                "state": job.get("state"),
                                "error": job.get("error_message"),
                            }
                            for job in failed
                        ],
                    },
                    indent=2,
                ),
                flush=True,
            )
            raise SystemExit(1)
        if len(jobs) == EXPECTED and states == {"COMPLETED": EXPECTED}:
            print(json.dumps({"status": "COMPLETED", "jobs": EXPECTED}), flush=True)
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
