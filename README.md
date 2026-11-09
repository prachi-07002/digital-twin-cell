# digital-twin-cell — a digital twin of a robotic manufacturing cell

**A live mirror of a factory cell: stream the robot, track it, score it.**

A 6-axis robot cell streams joint angles, motor temperatures, cycle times,
downtime events and part counts over an in-process pub/sub bus. A digital
twin subscribes, tracks the cell state, and computes the KPIs a smart
factory actually runs on — throughput, OEE (availability × performance ×
quality), and a downtime breakdown — then renders it all as a static HTML
dashboard. No MQTT broker, no network, no external services: pure Python
stdlib + NumPy, seeded and reproducible.

Built as a portfolio project for the Spring 2027 FTR project **"AI
implementation for smart manufacturing"** (Prof. Martin Byung-Guk Jun /
Tyson Oh) — industrial robots, data analysis, and digitalization of
physical assets. This is the digitalization half: the twin is the layer
an AI model (predictive maintenance, anomaly detection, scheduling) would
sit on top of, fed by exactly this stream.

## How to run

```bash
python3 demo.py                    # 8-hour shift, seed 42 -> report.html
python3 demo.py --minutes 60 --seed 7 --out report.html
python3 -m unittest discover -s tests -v
```

Requires Python 3.10+ and NumPy (`numpy 1.26.4` verified). No other
dependencies; no binary files anywhere in the repo.

## What it models

- **Simulator** (`digital_twin_cell/simulator.py`): 6-axis arm on a
  sinusoidal pick-and-place trajectory (joint angles clamped to real
  limits), ideal cycle 12 s with jitter, defect rate 2% (5% when motors
  overheat), motor temperatures that rise under load and cool during
  stops, and downtime events (jam, tool change, sensor fault, material
  starved, maintenance) with exponential inter-arrival / duration.
- **Pub/sub** (`digital_twin_cell/pubsub.py`): synchronous in-process
  broker with exact topics and `cell/*` wildcards — the same
  publish/subscribe shape as MQTT, with zero infrastructure.
- **Digital twin** (`digital_twin_cell/twin.py`): subscribes to `cell/*`,
  tracks live state, and computes throughput, OEE = availability ×
  performance × quality, downtime by cause, MTBF / MTTR, cycle-time
  stats, and temperature alerts.
- **Dashboard** (`digital_twin_cell/report.py`): self-contained
  `report.html` — live/final state, throughput, OEE waterfall, downtime
  breakdown with bar chart. No JS libraries, no network.

## Results — measured, 2026-11-08

Default demo run: one simulated **8-hour shift (480 min), seed 42**,
in **0.55 s** wall clock, **5,095 messages** published.

| Metric | Measured |
|---|---|
| Parts produced | **2,320** (2,275 good, 45 defective) |
| Throughput | **290.0 parts/hour** (284.4 good/hour) |
| OEE | **94.8%** = Availability 96.4% × Performance 100.2% × Quality 98.1% |
| Downtime | **17.1 min over 5 events** |
| MTBF / MTTR | 92.6 min / 3.4 min |
| Mean cycle time | 11.96 s (ideal 12 s) |
| Max motor temp | 69.0 °C (0 overheat alerts) |

Downtime breakdown (seed 42 shift):

| Cause | Duration | Share | Events |
|---|---|---|---|
| Jam | 16.1 min | 94.2% | 4 |
| Sensor fault | 1.0 min | 5.8% | 1 |

Note the honest nuance: this seeded shift was a *good* shift — one long
jam dominates the downtime, and OEE 94.8% is above the ~85% world-class
benchmark. Change the seed (`--seed 7`, `--seed 123`) and the twin
re-scores a different shift; the point is the measurement, not the
headline.

Tests: **15/15 pass** (`python3 -m unittest discover -s tests`), covering
pub/sub delivery/wildcards/unsubscribe, joint limits, seed
reproducibility, OEE math hand-checked on synthetic data (A=0.8333,
P=1.0, Q=0.96 → OEE=0.80), downtime-breakdown summation, and an
end-to-end twin-vs-simulator count match.

## Files

```
demo.py                          runnable demo -> report.html
report.html                      generated dashboard (from the demo run)
digital_twin_cell/
  __init__.py
  pubsub.py                      in-process broker (exact + wildcard topics)
  simulator.py                   6-axis robot cell simulator
  twin.py                        digital twin: state tracking + OEE/KPIs
  report.py                      static HTML dashboard generator
tests/
  test_digital_twin_cell.py      15 unit tests
```

## Application talking point

"Built a digital twin of a 6-axis robot cell — simulator streaming joint,
temperature and downtime data over pub/sub, twin computing live OEE at
94.8% and a downtime breakdown on a seeded 8-hour shift — the data layer
a predictive-maintenance model would sit on."
