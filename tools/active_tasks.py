"""List a run's PENDING/RUNNING Earth Engine tasks, in the project that actually runs them.

A run's tasks live in its compute project (param['compute_project'], default
project_name), not necessarily the project that holds its assets. Check here
before relaunching a run: resume skips only *finished* assets, so relaunching
while tasks are still active submits duplicates.

Running tasks don't record their destination, so this lists everything in the
compute project. When several runs share one compute project, a run is only
safe to relaunch once that project has no active tasks at all.

Usage:
  python tools/active_tasks.py <config.py> [<config.py> ...]

Exit status is 0 when no listed run has active tasks, 1 otherwise.
"""
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bugnet"))

from cli_utils import compute_project, load_parameters  # noqa: E402

ACTIVE_STATES = ("PENDING", "RUNNING")


def active_tasks(project):
    ee.Initialize(project=project)
    return [op["metadata"] for op in ee.data.listOperations()
            if op.get("metadata", {}).get("state") in ACTIVE_STATES]


def main(configs):
    busy = False
    for config in configs:
        param = load_parameters(config)
        project = compute_project(param)
        tasks = active_tasks(project)
        print(f"{param['project_name']} (compute project {project}): {len(tasks)} active")
        for m in tasks:
            print(f"  {m.get('state'):8s} {m.get('description')}")
        busy = busy or bool(tasks)
    return 1 if busy else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
