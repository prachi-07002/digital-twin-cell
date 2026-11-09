"""Simulated 6-axis robot cell streaming state over the in-process broker.

The cell runs a repeating pick-and-place cycle (ideal cycle time 12 s),
streams joint angles / motor temperatures as telemetry, counts parts
(good vs defective), and injects realistic downtime events. Everything
is seeded, so a given ``(seed, shift_minutes)`` reproduces exactly.

Topics published
-----------------
``cell/telemetry``  every 10 s while running or down: joints, temps, state
``cell/part``       on each completed cycle: good/defective, cycle time
``cell/downtime``   on downtime start and end: cause, duration
``cell/shift_end``  once, at the end of the simulated shift
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from .pubsub import Broker

# Joint limits (degrees) for a typical 6-axis industrial arm.
JOINT_LIMITS_DEG = [(-170, 170), (-120, 120), (-170, 170),
                    (-120, 120), (-120, 120), (-175, 175)]
# Sinusoidal pick-and-place trajectory: centre / amplitude per joint.
JOINT_CENTRES_DEG = np.array([0.0, -45.0, 60.0, 0.0, 45.0, 0.0])
JOINT_AMPS_DEG = np.array([60.0, 35.0, 40.0, 50.0, 30.0, 90.0])
JOINT_PHASES = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])

# Downtime causes: (mean duration in minutes, share of events).
DOWNTIME_CAUSES = {
    "tool_change": (12.0, 0.25),
    "jam": (8.0, 0.30),
    "sensor_fault": (5.0, 0.20),
    "material_starved": (6.0, 0.15),
    "maintenance": (20.0, 0.10),
}
TEMP_ALERT_C = 75.0  # motor temperature that raises an overheat flag


@dataclass
class DowntimeEvent:
    cause: str
    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass
class ShiftResult:
    """Summary counters returned by :meth:`RobotCellSimulator.run`."""

    shift_minutes: float
    parts_total: int
    parts_good: int
    parts_defective: int
    downtime_events: List[DowntimeEvent] = field(default_factory=list)
    temp_alerts: int = 0
    max_temp_c: float = 0.0

    @property
    def downtime_minutes(self) -> float:
        return sum(e.duration_s for e in self.downtime_events) / 60.0


class RobotCellSimulator:
    """A robot cell that publishes its state to a :class:`Broker`."""

    def __init__(self, broker: Broker, seed: int = 42, shift_minutes: float = 480.0,
                 ideal_cycle_s: float = 12.0, defect_rate: float = 0.02,
                 mean_time_between_failures_min: float = 90.0,
                 telemetry_period_s: float = 10.0) -> None:
        self.broker = broker
        self.rng = np.random.default_rng(seed)
        self.shift_s = shift_minutes * 60.0
        self.ideal_cycle_s = ideal_cycle_s
        self.defect_rate = defect_rate
        self.mtbf_s = mean_time_between_failures_min * 60.0
        self.telemetry_period_s = telemetry_period_s
        self.temps_c = np.full(6, 42.0)  # motor temps start at ambient-ish 42 C

    # -- trajectory / thermal helpers -------------------------------------
    def joint_angles(self, cycle_phase: float) -> List[float]:
        """Joint angles (deg) at a point 0..1 through the current cycle."""
        angles = JOINT_CENTRES_DEG + JOINT_AMPS_DEG * np.sin(
            2 * np.pi * cycle_phase + JOINT_PHASES)
        # Clamp to limits (the chosen trajectory stays inside them anyway).
        lo = np.array([a for a, _ in JOINT_LIMITS_DEG], dtype=float)
        hi = np.array([b for _, b in JOINT_LIMITS_DEG], dtype=float)
        return np.clip(angles, lo, hi).round(2).tolist()

    def _step_temps(self, running: bool, dt: float) -> None:
        target = 68.0 if running else 45.0
        self.temps_c += (target - self.temps_c) * 0.002 * dt
        self.temps_c += self.rng.normal(0.0, 0.02, size=6) * dt
        self.temps_c = np.clip(self.temps_c, 30.0, 95.0)

    def _pick_downtime(self) -> DowntimeEvent:
        causes = list(DOWNTIME_CAUSES)
        weights = np.array([DOWNTIME_CAUSES[c][1] for c in causes])
        cause = str(self.rng.choice(causes, p=weights / weights.sum()))
        mean_min = DOWNTIME_CAUSES[cause][0]
        duration_s = float(self.rng.exponential(mean_min) * 60.0)
        return DowntimeEvent(cause=cause, start_s=0.0, duration_s=max(60.0, duration_s))

    # -- main loop ---------------------------------------------------------
    def run(self) -> ShiftResult:
        t = 0.0
        parts_total = parts_good = parts_defective = 0
        events: List[DowntimeEvent] = []
        temp_alerts = 0
        max_temp = float(self.temps_c.max())
        next_telemetry = 0.0
        next_failure = t + float(self.rng.exponential(self.mtbf_s))
        cycle_remaining = self._sample_cycle_time()
        cycle_total = cycle_remaining

        def telemetry(state: str, phase: float) -> None:
            nonlocal next_telemetry
            self.broker.publish("cell/telemetry", {
                "time_s": round(t, 1),
                "state": state,
                "joint_angles_deg": self.joint_angles(phase),
                "motor_temps_c": [round(float(x), 1) for x in self.temps_c],
                "parts_completed": parts_total,
            }, timestamp_s=t)
            next_telemetry = t + self.telemetry_period_s

        while t < self.shift_s:
            # --- downtime branch (a failure aborts the in-progress cycle) ---
            if t >= next_failure:
                ev = self._pick_downtime()
                ev.start_s = t
                duration = min(ev.duration_s, self.shift_s - t)
                ev.duration_s = duration
                events.append(ev)
                self.broker.publish("cell/downtime", {
                    "event": "start", "cause": ev.cause,
                    "start_s": round(t, 1), "duration_s": round(duration, 1),
                }, timestamp_s=t)
                end = t + duration
                while t < end:
                    dt = min(self.telemetry_period_s, end - t)
                    self._step_temps(running=False, dt=dt)
                    t += dt
                    max_temp = max(max_temp, float(self.temps_c.max()))
                    if t >= next_telemetry:
                        telemetry("down", 0.0)
                self.broker.publish("cell/downtime", {
                    "event": "end", "cause": ev.cause,
                    "start_s": round(ev.start_s, 1), "duration_s": round(duration, 1),
                }, timestamp_s=t)
                next_failure = t + float(self.rng.exponential(self.mtbf_s))
                cycle_remaining = self._sample_cycle_time()
                cycle_total = cycle_remaining
                continue

            # --- running branch: advance one step (1 s, or to cycle end) ---
            dt = min(1.0, cycle_remaining, self.shift_s - t)
            if dt <= 0:
                break
            self._step_temps(running=True, dt=dt)
            t += dt
            cycle_remaining -= dt
            max_temp = max(max_temp, float(self.temps_c.max()))
            if float(self.temps_c.max()) > TEMP_ALERT_C:
                temp_alerts += 1
            if t >= next_telemetry:
                phase = 1.0 - (cycle_remaining / cycle_total) if cycle_total else 1.0
                telemetry("running", phase)
            if cycle_remaining <= 0 and t < self.shift_s:
                # Part completed at the end of this cycle.
                parts_total += 1
                defect_p = self.defect_rate
                if float(self.temps_c.max()) > TEMP_ALERT_C:
                    defect_p = 0.05  # hot motors make more bad parts
                good = bool(self.rng.random() >= defect_p)
                if good:
                    parts_good += 1
                else:
                    parts_defective += 1
                self.broker.publish("cell/part", {
                    "time_s": round(t, 1),
                    "part_id": parts_total,
                    "quality": "good" if good else "defective",
                    "cycle_time_s": round(cycle_total, 2),
                }, timestamp_s=t)
                cycle_remaining = self._sample_cycle_time()
                cycle_total = cycle_remaining

        self.broker.publish("cell/shift_end", {
            "shift_minutes": self.shift_s / 60.0,
            "parts_total": parts_total,
            "parts_good": parts_good,
            "parts_defective": parts_defective,
            "downtime_events": len(events),
        }, timestamp_s=t)
        return ShiftResult(
            shift_minutes=self.shift_s / 60.0,
            parts_total=parts_total, parts_good=parts_good,
            parts_defective=parts_defective, downtime_events=events,
            temp_alerts=temp_alerts, max_temp_c=round(max_temp, 1))

    def _sample_cycle_time(self) -> float:
        # Real cycle time jitters around the ideal 12 s.
        return float(np.clip(self.rng.normal(self.ideal_cycle_s, 1.0), 9.0, 16.0))
