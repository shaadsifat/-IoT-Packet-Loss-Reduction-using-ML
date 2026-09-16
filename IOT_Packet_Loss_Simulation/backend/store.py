"""
STEP 5 - persistence. Saves the workload built in workload.py and the
records produced live by transmission.py, so results survive a server
restart and can be exported later.

No database - batches are small JSON files on disk under data/. That's
enough for a local simulation tool and keeps the whole project readable
without extra services to run.
"""
import json
import os
import time
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BATCH_DIR = os.path.join(BASE_DIR, "data", "batches")
RESULT_DIR = os.path.join(BASE_DIR, "data", "results")

os.makedirs(BATCH_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)


def _batch_path(batch_id):
    return os.path.join(BATCH_DIR, f"{batch_id}.json")


def _result_path(batch_id, strategy):
    return os.path.join(RESULT_DIR, f"{batch_id}__{strategy}.json")


def create_batch(name, packets_per_device, sequence):
    batch_id = uuid.uuid4().hex[:10]
    record = {
        "id": batch_id,
        "name": name,
        "packets_per_device": packets_per_device,
        "device_count": len(sequence) // packets_per_device if packets_per_device else 0,
        "total_per_strategy": len(sequence),
        "created_at": time.time(),
        "sequence": sequence,
        "strategies_run": [],
    }
    with open(_batch_path(batch_id), "w", encoding="utf-8") as f:
        json.dump(record, f)
    return record


def get_batch(batch_id):
    path = _batch_path(batch_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_batches():
    out = []
    for fname in sorted(os.listdir(BATCH_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(BATCH_DIR, fname), "r", encoding="utf-8") as f:
            b = json.load(f)
        out.append({
            "id": b["id"], "name": b["name"], "packets_per_device": b["packets_per_device"],
            "total_per_strategy": b["total_per_strategy"], "created_at": b["created_at"],
            "strategies_run": b.get("strategies_run", []),
        })
    return out


def mark_strategy_run(batch_id, strategy):
    b = get_batch(batch_id)
    if b is None:
        return
    if strategy not in b["strategies_run"]:
        b["strategies_run"].append(strategy)
    with open(_batch_path(batch_id), "w", encoding="utf-8") as f:
        json.dump(b, f)


def save_results(batch_id, strategy, rows):
    with open(_result_path(batch_id, strategy), "w", encoding="utf-8") as f:
        json.dump(rows, f)
    mark_strategy_run(batch_id, strategy)


def get_results(batch_id, strategy):
    path = _result_path(batch_id, strategy)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def has_results(batch_id, strategy):
    return os.path.exists(_result_path(batch_id, strategy))


def delete_batch(batch_id):
    """Removes a batch's JSON file and both strategies' result files, if present."""
    removed = False
    batch_file = _batch_path(batch_id)
    if os.path.exists(batch_file):
        os.remove(batch_file)
        removed = True
    for strategy in ("baseline", "math"):
        result_file = _result_path(batch_id, strategy)
        if os.path.exists(result_file):
            os.remove(result_file)
    return removed
