#!/usr/bin/env python3
"""Select a fast CPU group without changing the host's CPU/SMT settings."""

import argparse
import os
from pathlib import Path


def select_cpus(cpus, min_cores):
    """Rows are (logical CPU, physical core identity, max frequency)."""
    if not cpus:
        raise ValueError("No allowed CPUs")
    fastest = max(row[2] for row in cpus)
    selected = [row for row in cpus if row[2] == fastest]
    if fastest == 0 or len({row[1] for row in selected}) < min_cores:
        selected = cpus
    return sorted(row[0] for row in selected)


def host_cpus():
    rows = []
    for cpu in sorted(os.sched_getaffinity(0)):
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}")
        try:
            core = (root / "topology/core_id").read_text().strip()
            package = (root / "topology/physical_package_id").read_text().strip()
            frequency = int((root / "cpufreq/cpuinfo_max_freq").read_text())
        except (OSError, ValueError):
            # Incomplete topology must not silently exclude physical cores.
            return [(c, c, 0) for c in sorted(os.sched_getaffinity(0))]
        rows.append((cpu, (package, core), frequency))
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-cores", type=int, default=4)
    options = parser.parse_args()
    print(",".join(map(str, select_cpus(host_cpus(), options.min_cores))))
