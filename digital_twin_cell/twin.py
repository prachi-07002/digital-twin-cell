"""Digital twin: subscribes to the cell's pub/sub stream and tracks state.

Computes the standard manufacturing KPIs from the live stream:

* throughput      -- parts produced per hour (total and good-only)
* OEE             -- availability x performance x quality
    availability = run time / planned production time
    performance  = (ideal cycle time x parts) / run time
    quality      = good parts / total parts
* downtime breakdown -- minutes / share / count per cause
* MTBF / MTTR, cycle-time stats, motor-temperature tracking

The twin can be fed either by subscribing it to a :class:`Broker`
(``twin.attach(broker)``) or by calling its ``on_*`` handlers directly,
which is what the unit tests do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .pubsub import Broker, Message
from .simulator import TEMP_ALERT_C


@dataclass
class DowntimeSummary:
    cause: str
    minutes: float
    share_of_downtime: float  # 0..1
    count: int


@dataclass
class TwinSnapshot:
    """Everything the dashboard needs, in one plain object."""

    elapsed_s: float
    state: str
    parts_total: int
    parts_good: int
    parts_defective: int
    throughput_per_hour: float
    good_throughput_per_hour: float
    availability: float
    performance: float
    quality: float
    oee: float
    downtime_minutes: float
    downtime_breakdown: List[DowntimeSummary]
    mtbf_min: Optional[float]
    mttr_min: Optional[float]
    mean_cycle_s: Optional[float]
    max_temp_c: float
    temp_alerts: int
    joint_angles_deg: List[float]
    motor_temps_c: List[float]


class DigitalTwin:
    """Live model of one robot cell, updated from pub/sub messages."""

    def __init__(self, ideal_cycle_s: float = 12.0, planned_minutes: float = 480.0) -> None:
        self.ideal_cycle_s = ideal_cycle_s
        self.planned_s = planned_minutes * 60.0
        self.elapsed_s = 0.0
        self.state = "idle"
        self.parts_total = 0
        self.parts_good = 0
        self.parts_defective = 0
        self.cycle_times: List[float] = []
        self.downtime_s_by_cause: Dict[str, float] = {}
        self.downtime_counts: Dict[str, int] = {}
        self.downtime_events = 0
        self.max_temp_c = 0.0
        self.temp_alerts = 0
        self.joint_angles_deg: List[float] = [0.0] * 6
        self.motor_temps_c: List[float] = [0.0] * 6
        self._down_start: Dict[str, float] = {}

    # -- wiring ------------------------------------------------------------
    def attach(self, broker: Broker) -> None:
        broker.subscribe("cell/*", self._on_message)

    def _on_message(self, msg: Message) -> None:
        if msg.topic == "cell/telemetry":
            self.on_telemetry(msg.payload)
        elif msg.topic == "cell/part":
            self.on_part(msg.payload)
        elif msg.topic == "cell/downtime":
            self.on_downtime(msg.payload)
        elif msg.topic == "cell/shift_end":
            self.on_shift_end(msg.payload)

    # -- handlers ----------------------------------------------------------
    def on_telemetry(self, payload: dict) -> None:
        self.elapsed_s = max(self.elapsed_s, float(payload.get("time_s", 0.0)))
        self.state = str(payload.get("state", self.state))
        self.joint_angles_deg = [float(x) for x in payload.get("joint_angles_deg", [])] or self.joint_angles_deg
        self.motor_temps_c = [float(x) for x in payload.get("motor_temps_c", [])] or self.motor_temps_c
        if self.motor_temps_c:
            self.max_temp_c = max(self.max_temp_c, max(self.motor_temps_c))
            if max(self.motor_temps_c) > TEMP_ALERT_C:
                self.temp_alerts += 1

    def on_part(self, payload: dict) -> None:
        self.elapsed_s = max(self.elapsed_s, float(payload.get("time_s", 0.0)))
        self.parts_total += 1
        if payload.get("quality") == "good":
            self.parts_good += 1
        else:
            self.parts_defective += 1
        if "cycle_time_s" in payload:
            self.cycle_times.append(float(payload["cycle_time_s"]))

    def on_downtime(self, payload: dict) -> None:
        cause = str(payload.get("cause", "unknown"))
        if payload.get("event") == "start":
            self._down_start[cause] = float(payload.get("start_s", self.elapsed_s))
        elif payload.get("event") == "end":
            duration = float(payload.get("duration_s", 0.0))
            if duration <= 0 and cause in self._down_start:
                duration = float(payload.get("start_s", self.elapsed_s)) - self._down_start[cause]
            self.downtime_s_by_cause[cause] = self.downtime_s_by_cause.get(cause, 0.0) + duration
            self.downtime_counts[cause] = self.downtime_counts.get(cause, 0) + 1
            self.downtime_events += 1
            self._down_start.pop(cause, None)

    def on_shift_end(self, payload: dict) -> None:
        self.elapsed_s = max(self.elapsed_s, float(payload.get("shift_minutes", 0.0)) * 60.0)
        self.state = "shift_end"

    # -- KPIs ---------------------------------------------------------------
    @property
    def downtime_s(self) -> float:
        return sum(self.downtime_s_by_cause.values())

    @property
    def run_s(self) -> float:
        return max(0.0, self.elapsed_s - self.downtime_s)

    @property
    def availability(self) -> float:
        if self.elapsed_s <= 0:
            return 0.0
        return self.run_s / self.elapsed_s

    @property
    def performance(self) -> float:
        if self.run_s <= 0 or self.parts_total == 0:
            return 0.0
        return (self.ideal_cycle_s * self.parts_total) / self.run_s

    @property
    def quality(self) -> float:
        if self.parts_total == 0:
            return 0.0
        return self.parts_good / self.parts_total

    @property
    def oee(self) -> float:
        return self.availability * self.performance * self.quality

    @property
    def throughput_per_hour(self) -> float:
        return self.parts_total / (self.elapsed_s / 3600.0) if self.elapsed_s > 0 else 0.0

    @property
    def good_throughput_per_hour(self) -> float:
        return self.parts_good / (self.elapsed_s / 3600.0) if self.elapsed_s > 0 else 0.0

    def downtime_breakdown(self) -> List[DowntimeSummary]:
        total = self.downtime_s
        out = []
        for cause in sorted(self.downtime_s_by_cause, key=lambda c: -self.downtime_s_by_cause[c]):
            secs = self.downtime_s_by_cause[cause]
            out.append(DowntimeSummary(
                cause=cause, minutes=secs / 60.0,
                share_of_downtime=(secs / total) if total > 0 else 0.0,
                count=self.downtime_counts.get(cause, 0)))
        return out

    @property
    def mtbf_min(self) -> Optional[float]:
        if self.downtime_events == 0:
            return None
        return (self.run_s / 60.0) / self.downtime_events

    @property
    def mttr_min(self) -> Optional[float]:
        if self.downtime_events == 0:
            return None
        return (self.downtime_s / 60.0) / self.downtime_events

    def snapshot(self) -> TwinSnapshot:
        return TwinSnapshot(
            elapsed_s=self.elapsed_s, state=self.state,
            parts_total=self.parts_total, parts_good=self.parts_good,
            parts_defective=self.parts_defective,
            throughput_per_hour=self.throughput_per_hour,
            good_throughput_per_hour=self.good_throughput_per_hour,
            availability=self.availability, performance=self.performance,
            quality=self.quality, oee=self.oee,
            downtime_minutes=self.downtime_s / 60.0,
            downtime_breakdown=self.downtime_breakdown(),
            mtbf_min=self.mtbf_min, mttr_min=self.mttr_min,
            mean_cycle_s=(float(np.mean(self.cycle_times)) if self.cycle_times else None),
            max_temp_c=self.max_temp_c, temp_alerts=self.temp_alerts,
            joint_angles_deg=list(self.joint_angles_deg),
            motor_temps_c=list(self.motor_temps_c))
