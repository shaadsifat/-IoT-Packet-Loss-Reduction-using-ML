"""
Router Loss Bench - Flask app.

This file only wires the pipeline together; it contains no simulation
rules of its own. Reading top to bottom mirrors the actual order a packet
goes through:

  devices.py      Step 0  the network topology (7 devices)
  workload.py     Step 1  fix the traffic pattern for a batch (pre-send)
  zone_rules.py   Step 2  the Stage-1 math rule (deterministic, pre-send)
  ml_model.py     Step 2b the trained Random Forest, for zones 3-5 under math_ai
  congestion.py   Step 3  live network condition, measured at send time
  transmission.py Step 4  live risk + the actual loss draw, at arrival
  events.py       Step 6  format what step 1-4's output looks like over SSE
  store.py        Step 5  persist a run's results to disk

POST /api/batches                          run Step 1, save the workload
GET  /api/batches/<id>/stream               run Steps 2-4 live, per packet,
                                             streaming Step 6's events as it goes
GET  /api/batches/<id>/results / /export    read back what Step 5 saved
"""
import random
import time

from flask import Flask, Response, jsonify, request, send_from_directory

import devices
import events
import ml_model
import store
import transmission
import workload
from congestion import next_congestion

app = Flask(__name__, static_folder="../frontend", static_url_path="")

ALL_COLS = workload.PRE_SEND_COLS + transmission.DECISION_COLS + transmission.POST_SEND_COLS
VALID_STRATEGIES = ("baseline", "math", "math_ai")


@app.get("/api/model-info")
def model_info():
    """Whether the Random Forest is loaded, and its notebook-06 metadata -
    the frontend's "About this model" panel reads this directly."""
    return jsonify({
        "available": ml_model.is_available(),
        "load_error": ml_model.load_error(),
        "info": ml_model.info(),
    })


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/batches")
def create_batch():
    """Step 1: fix this batch's traffic pattern, once, before anything is sent."""
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip() or "Untitled batch"
    packets_per_device = int(body.get("packets_per_device", 0))
    if packets_per_device < 1 or packets_per_device > 20000:
        return jsonify({"error": "packets_per_device must be between 1 and 20000"}), 400

    load = workload.build_batch_workload(packets_per_device)
    batch = store.create_batch(name, packets_per_device, load)
    return jsonify({
        "id": batch["id"], "name": batch["name"],
        "packets_per_device": batch["packets_per_device"],
        "total_per_strategy": batch["total_per_strategy"],
        "created_at": batch["created_at"], "strategies_run": batch["strategies_run"],
    })


@app.get("/api/batches")
def list_batches():
    return jsonify(store.list_batches())


@app.get("/api/batches/<batch_id>")
def batch_detail(batch_id):
    b = store.get_batch(batch_id)
    if b is None:
        return jsonify({"error": "batch not found"}), 404
    return jsonify({
        "id": b["id"], "name": b["name"], "packets_per_device": b["packets_per_device"],
        "total_per_strategy": b["total_per_strategy"], "created_at": b["created_at"],
        "strategies_run": b.get("strategies_run", []),
        "devices": [{"id": d["id"], "name": d["name"], "type": d["type"]} for d in devices.DEVICES],
    })


@app.delete("/api/batches/<batch_id>")
def delete_batch(batch_id):
    """Permanently removes a batch and both strategies' saved results."""
    removed = store.delete_batch(batch_id)
    if not removed:
        return jsonify({"error": "batch not found"}), 404
    return jsonify({"deleted": batch_id})


@app.get("/api/batches/<batch_id>/stream")
def stream_batch(batch_id):
    """Steps 2-4, live: for every pre-fixed packet in the batch's workload,
    run the zone rule, measure live congestion, draw the real outcome - in
    that order, one packet at a time, as this generator actually executes."""
    strategy = request.args.get("strategy", "baseline")
    if strategy not in VALID_STRATEGIES:
        return jsonify({"error": f"strategy must be one of {VALID_STRATEGIES}"}), 400
    try:
        speed_ms = max(0.0, min(300.0, float(request.args.get("speed_ms", 15))))
    except ValueError:
        speed_ms = 15.0

    b = store.get_batch(batch_id)
    if b is None:
        return jsonify({"error": "batch not found"}), 404

    def generate():
        # Fresh, unseeded entropy every run: re-running the same batch and
        # strategy will land on a similar loss % but not an identical one -
        # a fixed/precomputed simulation could not do that.
        rng = random.Random()
        congestion = 1.0
        records = []

        transit_ms = max(4.0, speed_ms * 0.5)
        tail_ms = max(0.0, speed_ms - transit_ms)

        yield events.meta_event(len(b["sequence"]))

        for context in b["sequence"]:
            yield events.sent_event(context)                       # packet leaves the router
            time.sleep(transit_ms / 1000.0)                        # travel time

            # Real protective delay, if this packet's action calls for one -
            # actual wall-clock time, not a probability discount.
            action = transmission.action_for(context, strategy)
            extra_delay_ms = transmission.ACTION_MECHANICS[action]["extra_delay_ms"]
            if extra_delay_ms > 0:
                time.sleep(extra_delay_ms / 1000.0)

            congestion = next_congestion(congestion, speed_ms, rng)  # Step 3, live
            record = transmission.resolve_packet(context, strategy, congestion, rng)  # Step 4, live
            records.append(record)

            yield events.landed_event(record)                      # packet has arrived, resolved
            if tail_ms > 0:
                time.sleep(tail_ms / 1000.0)

        store.save_results(batch_id, strategy, records)             # Step 5
        yield events.done_event()

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.get("/api/batches/<batch_id>/results")
def get_results(batch_id):
    strategy = request.args.get("strategy", "baseline")
    rows = store.get_results(batch_id, strategy)
    if rows is None:
        return jsonify({"error": "no results yet for this strategy"}), 404

    lost = sum(r["packet_lost"] for r in rows)
    total = len(rows)
    by_device = {}
    for r in rows:
        d = by_device.setdefault(r["device"], {"sent": 0, "lost": 0})
        d["sent"] += 1
        d["lost"] += r["packet_lost"]
    for d in by_device.values():
        d["loss_pct"] = round(d["lost"] / d["sent"] * 100, 2) if d["sent"] else 0

    return jsonify({
        "rows": rows, "total": total, "lost": lost,
        "loss_pct": round(lost / total * 100, 2) if total else 0,
        "by_device": by_device,
    })


@app.get("/api/batches/<batch_id>/export")
def export_csv(batch_id):
    import csv
    import io

    strategy = request.args.get("strategy", "baseline")
    rows = store.get_results(batch_id, strategy)
    if rows is None:
        return jsonify({"error": "no results yet for this strategy"}), 404

    b = store.get_batch(batch_id)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ALL_COLS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in ALL_COLS})

    filename = f"{b['name'].replace(' ', '_')}_{strategy}.csv"
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'
    })


if __name__ == "__main__":
    app.run(debug=True, threaded=True, port=5050)
