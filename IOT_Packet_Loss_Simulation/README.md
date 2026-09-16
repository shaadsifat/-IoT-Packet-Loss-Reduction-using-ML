# Router Loss Bench

A local simulation of a router sending packets to 7 IoT devices (3 Light Bulbs,
2 Ceiling Fans, 1 AC, 1 Heater), comparing three send strategies:

- **Strategy A — No protection / no analysis**: every packet is just sent.
- **Strategy B — Mathematical analysis**: the Stage-1 `Spkts`/`sttl` decision
  cascade from `IOT_Packet_Loss_ML_Model/05_manual_decision_rules.ipynb`
  classifies each packet into one of 5 risk zones and applies a protective
  action before sending.
- **Strategy C — Mathematical analysis + ML**: same Stage-1 action as
  Strategy B, but for zones 3-5 (MODERATE and up) the static zone rate is
  compared against a live prediction from the trained Random Forest
  (`IOT_Packet_Loss_ML_Model/06_export_deployment_model.ipynb`); whichever
  candidate resolves better for that specific packet is what gets reported.
  If the model file is unavailable, this strategy degrades to Strategy B's
  math automatically.

All three strategies run against the exact same **batch** — one fixed,
pre-generated traffic pattern — so the comparison isn't affected by
different random traffic between runs. Risk and the actual loss outcome are
not part of that fixed pattern — they are computed live, packet by packet,
while a run is streaming (see "How a packet's life goes" below).

## Project structure

The backend is split one file per step, in the order a packet actually goes
through them — not grouped by "backend stuff" vs "frontend stuff":

```
IOT_Packet_Loss_Simulation/
  backend/
    devices.py          Step 0   network topology - 7 devices + why each profile
    workload.py         Step 1   fix a batch's traffic pattern (pre-send only)
    zone_rules.py        Step 2   the Stage-1 math rule (deterministic)
    ml_model.py           Step 2b  loads the trained Random Forest, exposes predict_risk()
    congestion.py         Step 3   live network condition, measured at send time
    transmission.py       Step 4   live risk + the actual loss draw, at arrival
    store.py              Step 5   persists a run's results to disk (data/*.json)
    events.py             Step 6   formats Steps 1-4's output as SSE events
    app.py                Flask routes - wires Steps 0-6 together, no rules of its own
    model/                 random_forest_pipeline.joblib + model_info.json
    data/                  created at runtime - batches and results live here
  frontend/
    index.html
    styles.css
    app.js
  requirements.txt
```

`devices.py`, `workload.py`, `zone_rules.py`, `ml_model.py`, `congestion.py`,
and `transmission.py` each carry a docstring explaining what step they are
and why they don't know anything beyond that step — reading them in that
order follows a packet's whole life.

## Running it

```
cd IOT_Packet_Loss_Simulation
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python backend/app.py
```

Then open **http://localhost:5050** in a browser.

## Using it

1. **Create a batch** — name it, set packets-per-device (this is *per
   device*, so 500 means 500 × 7 devices = 3,500 sends per strategy).
2. **Run Strategy A**, then **Strategy B**, then **Strategy C** on the same
   batch — each run streams live at an adjustable pace (the speed slider).
   During a run:
   - each device's tick bar fills in — grey while a packet is in flight to
     it, green/red the instant that specific packet resolves;
   - the live "network congestion" readout moves with the selected pacing;
   - the packet log ticker shows packets landing one at a time.
3. Once strategies have run, the summary cards, per-device chart, and full
   packet log (filterable, sortable, paginated, color-coded by pre-send /
   live-decision / post-send) fill in for comparison. The `#` column's
   colored dot is the same color for the same packet index across all three
   strategies, making the paired comparison identifiable at a glance.
4. **Save results (CSV)** exports the full per-packet log for one strategy's
   run on that batch, in the same 3-group column order.
5. **Delete a batch** removes it and all of its strategy results, on disk
   and in the UI, after confirmation.

## How a packet's life actually goes (Steps 1-4)

For every packet in a batch, in this exact order, live, inside the running
stream (`app.py`'s `stream_batch`):

1. **Step 1 (already fixed by the batch):** which device, its `Spkts`
   session counter, `sttl`, and rolling `ct_*` traffic counters — exactly
   the pre-send feature set from the ML notebooks. A `sent` event fires
   with only this information; the device's tick goes grey.
2. **Step 2 (deterministic, pre-send):** `zone_rules.classify(spkts, sttl)`
   looks up which of the 5 Stage-1 zones this packet falls into and what
   action applies — a pure function of already-known values, identical for
   Strategy B and Strategy C.
3. **Transit delay** — represents the packet's travel time to the device,
   plus any protective delay the zone's action adds.
4. **Step 3 (live):** `congestion.next_congestion()` measures network
   congestion *right now*, pulled toward a target set by this run's actual
   pacing (fast pacing → higher congestion → more loss; slow pacing →
   lower congestion → less loss) plus fresh jitter.
5. **Step 4 (live):** `transmission.resolve_packet()` combines the zone's
   risk rate with that live congestion, applies the zone's mitigation
   (duplicate sends and/or delay) if relevant, and draws the real outcome
   with a fresh, unseeded random call — the actual "did it survive the
   trip" coin-flip, happening at this instant, not read from a table. Under
   Strategy C on an AI-eligible zone, the static rate and the model's rate
   are each drawn this way independently, and the better-resolving one is
   what's reported (see `transmission.py`'s docstring for the exact rule).
   A `landed` event fires with the result; the device's tick turns green or
   red.

Because Steps 3-4 are unseeded and pace-dependent, re-running the same
batch and strategy twice lands on a *similar* loss % but not an identical
one — real network variance, not a replay of cached numbers.
