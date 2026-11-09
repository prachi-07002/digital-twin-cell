"""Unit tests for digital-twin-cell. Run:  python3 -m unittest discover -s tests -v"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from digital_twin_cell.pubsub import Broker
from digital_twin_cell.report import render_report, write_report
from digital_twin_cell.simulator import JOINT_LIMITS_DEG, RobotCellSimulator
from digital_twin_cell.twin import DigitalTwin


class TestPubSub(unittest.TestCase):
    def test_exact_topic_delivery(self):
        broker = Broker()
        seen = []
        broker.subscribe("cell/part", lambda m: seen.append(m.payload["part_id"]))
        broker.publish("cell/part", {"part_id": 7})
        broker.publish("cell/telemetry", {"part_id": 99})
        self.assertEqual(seen, [7])

    def test_wildcard_delivery(self):
        broker = Broker()
        seen = []
        broker.subscribe("cell/*", lambda m: seen.append(m.topic))
        broker.publish("cell/part", {})
        broker.publish("cell/telemetry", {})
        broker.publish("other/topic", {})
        self.assertEqual(seen, ["cell/part", "cell/telemetry"])

    def test_unsubscribe_stops_delivery(self):
        broker = Broker()
        seen = []
        cb = lambda m: seen.append(1)
        broker.subscribe("cell/part", cb)
        broker.publish("cell/part", {})
        self.assertTrue(broker.unsubscribe("cell/part", cb))
        broker.publish("cell/part", {})
        self.assertEqual(seen, [1])
        self.assertFalse(broker.unsubscribe("cell/part", cb))

    def test_publish_counts_and_sequences(self):
        broker = Broker()
        m1 = broker.publish("cell/part", {})
        m2 = broker.publish("cell/part", {})
        self.assertEqual(broker.published, 2)
        self.assertEqual((m1.seq, m2.seq), (1, 2))


class TestSimulator(unittest.TestCase):
    def test_short_shift_produces_parts_and_telemetry(self):
        broker = Broker()
        parts, telem = [], []
        broker.subscribe("cell/part", lambda m: parts.append(m.payload))
        broker.subscribe("cell/telemetry", lambda m: telem.append(m.payload))
        sim = RobotCellSimulator(broker, seed=1, shift_minutes=60)
        result = sim.run()
        self.assertGreater(result.parts_total, 100)  # ~5/min ideal, minus downtime
        self.assertEqual(result.parts_total, result.parts_good + result.parts_defective)
        self.assertEqual(len(parts), result.parts_total)
        self.assertGreater(len(telem), 100)
        self.assertEqual(result.parts_total, len(parts))

    def test_joint_angles_within_limits(self):
        sim = RobotCellSimulator(Broker(), seed=1)
        for phase in [i / 20 for i in range(21)]:
            angles = sim.joint_angles(phase)
            self.assertEqual(len(angles), 6)
            for angle, (lo, hi) in zip(angles, JOINT_LIMITS_DEG):
                self.assertGreaterEqual(angle, lo)
                self.assertLessEqual(angle, hi)

    def test_same_seed_reproduces_same_shift(self):
        def run_once():
            broker = Broker()
            return RobotCellSimulator(broker, seed=42, shift_minutes=60).run()
        a, b = run_once(), run_once()
        self.assertEqual(a.parts_total, b.parts_total)
        self.assertEqual(a.parts_good, b.parts_good)
        self.assertEqual(len(a.downtime_events), len(b.downtime_events))

    def test_downtime_events_are_valid(self):
        broker = Broker()
        sim = RobotCellSimulator(broker, seed=7, shift_minutes=480)
        result = sim.run()
        self.assertGreater(len(result.downtime_events), 0)
        for ev in result.downtime_events:
            self.assertGreater(ev.duration_s, 0)
            self.assertIn(ev.cause, {"tool_change", "jam", "sensor_fault",
                                     "material_starved", "maintenance"})
        self.assertLessEqual(result.downtime_minutes, 480.0)

    def test_temperatures_stay_in_physical_range(self):
        broker = Broker()
        temps = []
        broker.subscribe("cell/telemetry",
                         lambda m: temps.extend(m.payload["motor_temps_c"]))
        RobotCellSimulator(broker, seed=3, shift_minutes=120).run()
        self.assertTrue(temps)
        self.assertTrue(all(30.0 <= t <= 95.0 for t in temps))


class TestTwin(unittest.TestCase):
    def test_oee_math_on_synthetic_data(self):
        # Hand-computed: 3600 s elapsed, 600 s downtime -> A = 3000/3600.
        # 250 parts at 12 s ideal in 3000 s run -> P = 3000/3000 = 1.0.
        # 240 good / 250 -> Q = 0.96. OEE = 0.8333 * 1.0 * 0.96 = 0.80.
        twin = DigitalTwin(ideal_cycle_s=12.0)
        twin.on_downtime({"event": "start", "cause": "jam", "start_s": 0.0})
        twin.on_downtime({"event": "end", "cause": "jam", "start_s": 0.0, "duration_s": 600.0})
        for i in range(250):
            twin.on_part({"time_s": 3600.0, "quality": "good" if i < 240 else "defective",
                          "cycle_time_s": 12.0})
        self.assertAlmostEqual(twin.availability, 3000 / 3600, places=6)
        self.assertAlmostEqual(twin.performance, 1.0, places=6)
        self.assertAlmostEqual(twin.quality, 0.96, places=6)
        self.assertAlmostEqual(twin.oee, 0.80, places=6)
        self.assertAlmostEqual(twin.throughput_per_hour, 250.0, places=6)

    def test_downtime_breakdown_sums_to_total(self):
        twin = DigitalTwin()
        twin.on_downtime({"event": "start", "cause": "jam", "start_s": 0.0})
        twin.on_downtime({"event": "end", "cause": "jam", "start_s": 0.0, "duration_s": 600.0})
        twin.on_downtime({"event": "start", "cause": "tool_change", "start_s": 0.0})
        twin.on_downtime({"event": "end", "cause": "tool_change", "start_s": 0.0, "duration_s": 300.0})
        twin.elapsed_s = 3600.0
        bd = twin.downtime_breakdown()
        self.assertAlmostEqual(sum(d.minutes for d in bd), 15.0)
        self.assertAlmostEqual(sum(d.share_of_downtime for d in bd), 1.0)
        self.assertEqual(bd[0].cause, "jam")  # largest first
        self.assertEqual(twin.mttr_min, 7.5)
        self.assertEqual(twin.downtime_events, 2)

    def test_empty_twin_has_zero_kpis_not_nan(self):
        twin = DigitalTwin()
        self.assertEqual(twin.oee, 0.0)
        self.assertEqual(twin.throughput_per_hour, 0.0)
        self.assertEqual(twin.downtime_breakdown(), [])
        self.assertIsNone(twin.mtbf_min)
        self.assertIsNone(twin.mean_cycle_s if hasattr(twin, "mean_cycle_s") else None)

    def test_end_to_end_twin_matches_simulator_counts(self):
        broker = Broker()
        twin = DigitalTwin(ideal_cycle_s=12.0, planned_minutes=60)
        twin.attach(broker)
        result = RobotCellSimulator(broker, seed=5, shift_minutes=60).run()
        snap = twin.snapshot()
        self.assertEqual(snap.parts_total, result.parts_total)
        self.assertEqual(snap.parts_good, result.parts_good)
        self.assertEqual(snap.parts_defective, result.parts_defective)
        self.assertAlmostEqual(snap.downtime_minutes, result.downtime_minutes, places=1)
        self.assertGreater(snap.oee, 0.0)
        self.assertLessEqual(snap.oee, 1.0)
        self.assertGreater(snap.throughput_per_hour, 0.0)


class TestReport(unittest.TestCase):
    def test_report_contains_kpis_and_downtime(self):
        twin = DigitalTwin()
        twin.on_downtime({"event": "start", "cause": "jam", "start_s": 0.0})
        twin.on_downtime({"event": "end", "cause": "jam", "start_s": 0.0, "duration_s": 600.0})
        for i in range(10):
            twin.on_part({"time_s": 3600.0, "quality": "good", "cycle_time_s": 12.0})
        html_out = render_report(twin.snapshot())
        self.assertIn("OEE", html_out)
        self.assertIn("Jam", html_out)
        self.assertIn("Throughput", html_out)
        self.assertIn("10", html_out)

    def test_write_report_creates_file(self):
        twin = DigitalTwin()
        twin.on_part({"time_s": 60.0, "quality": "good", "cycle_time_s": 12.0})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "report.html")
            self.assertEqual(write_report(twin.snapshot(), path), path)
            self.assertGreater(os.path.getsize(path), 1000)


if __name__ == "__main__":
    unittest.main()
