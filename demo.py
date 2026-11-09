#!/usr/bin/env python3
"""Demo: run a simulated robot-cell shift, track it with the digital twin,
print the KPIs, and write the HTML dashboard to report.html.

Usage:
    python3 demo.py [--minutes 480] [--seed 42] [--out report.html]
"""

from __future__ import annotations

import argparse
import time

from digital_twin_cell.pubsub import Broker
from digital_twin_cell.report import write_report
from digital_twin_cell.simulator import RobotCellSimulator
from digital_twin_cell.twin import DigitalTwin


def run_demo(shift_minutes: float = 480.0, seed: int = 42, out: str = "report.html"):
    broker = Broker()
    twin = DigitalTwin(ideal_cycle_s=12.0, planned_minutes=shift_minutes)
    twin.attach(broker)
    sim = RobotCellSimulator(broker, seed=seed, shift_minutes=shift_minutes)

    started = time.perf_counter()
    result = sim.run()
    wall_s = time.perf_counter() - started
    snap = twin.snapshot()
    write_report(
        snap, out,
        subtitle=(f"Simulated {shift_minutes:.0f}-minute shift (seed {seed}) — "
                  f"{result.parts_total} parts, {result.downtime_minutes:.1f} min downtime."))

    print(f"Shift simulated: {shift_minutes:.0f} min (seed {seed}) in {wall_s:.2f} s wall clock")
    print(f"Messages published: {broker.published}")
    print(f"Parts: {result.parts_total} total, {result.parts_good} good, "
          f"{result.parts_defective} defective")
    print(f"Throughput: {snap.throughput_per_hour:.1f} parts/hour "
          f"({snap.good_throughput_per_hour:.1f} good/hour)")
    print(f"OEE: {100 * snap.oee:.1f}%  "
          f"(Availability {100 * snap.availability:.1f}% x "
          f"Performance {100 * snap.performance:.1f}% x "
          f"Quality {100 * snap.quality:.1f}%)")
    print(f"Downtime: {snap.downtime_minutes:.1f} min over {len(result.downtime_events)} events")
    for d in snap.downtime_breakdown:
        print(f"  - {d.cause:18s} {d.minutes:6.1f} min  ({100 * d.share_of_downtime:4.1f}%)  x{d.count}")
    mtbf = f"{snap.mtbf_min:.1f} min" if snap.mtbf_min is not None else "n/a"
    mttr = f"{snap.mttr_min:.1f} min" if snap.mttr_min is not None else "n/a"
    print(f"MTBF {mtbf} | MTTR {mttr} | mean cycle {snap.mean_cycle_s:.2f} s "
          f"| max motor temp {snap.max_temp_c:.1f} C | temp alerts {snap.temp_alerts}")
    print(f"Dashboard written to {out}")
    return snap, result


def main() -> None:
    ap = argparse.ArgumentParser(description="Digital twin demo: simulate a robot-cell shift.")
    ap.add_argument("--minutes", type=float, default=480.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="report.html")
    args = ap.parse_args()
    run_demo(args.minutes, args.seed, args.out)


if __name__ == "__main__":
    main()
