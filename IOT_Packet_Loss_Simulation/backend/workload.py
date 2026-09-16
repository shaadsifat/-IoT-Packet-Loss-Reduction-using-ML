"""
STEP 1 - Build a batch's WORKLOAD: what the router is about to send, and to
whom, before any of it is actually sent.

This is the only step that runs once, in advance, at batch-creation time -
and it is only allowed to decide things a real router genuinely already
knows before sending a packet: which device it's talking to next, that
device's running Spkts session counter, its sttl, and rolling counts of its
own recent traffic (the ct_* columns). None of that is an outcome - it is
the pre-send feature set carried over from the ML notebooks
(IOT_Packet_Loss_ML_Model/03, Section "pre-send candidates").

Explicitly NOT decided here: congestion, risk, or whether any packet is
lost. Those are computed later, live, in transmission.py, during the
actual streamed run - see that module for why.
"""
import random

from devices import DEVICES, fresh_device_state
from zone_rules import classify

WINDOW_SIZE = 80


def build_batch_workload(packets_per_device, seed=None):
    """
    Round-robins packets_per_device sends across every device in DEVICES and
    returns the fixed list of pre-send contexts - the shared "traffic" both
    strategies will later be evaluated against.
    """
    rng = random.Random(seed)
    device_state = fresh_device_state()
    for state in device_state.values():
        state["session_len"] = rng.randint(3, 12)

    recent_window = []
    workload = []
    total = packets_per_device * len(DEVICES)

    for i in range(total):
        dev = DEVICES[i % len(DEVICES)]
        state = device_state[dev["id"]]

        state["spkts"] += 1
        if state["spkts"] > state["session_len"]:
            state["spkts"] = 1
            state["session_len"] = rng.randint(3, 12)
        spkts = state["spkts"]
        sttl = max(0, round(dev["sttl_base"] + rng.uniform(-dev["sttl_jit"], dev["sttl_jit"])))

        proto, service, dst_bucket = dev["proto"], dev["service"], dev["dst_bucket"]
        smeansz = round(rng.uniform(40, 150))
        sbytes = round(smeansz * spkts * rng.uniform(0.85, 1.15))
        swin = rng.randint(0, 255) if proto == "tcp" else 0

        def count_in_window(pred):
            return sum(1 for p in recent_window if pred(p))

        ct_srv_src = count_in_window(lambda p: p["service"] == service)
        ct_srv_dst = count_in_window(lambda p: p["service"] == service and p["device"] == dev["id"])
        ct_dst_ltm = count_in_window(lambda p: p["device"] == dev["id"])
        last_20 = recent_window[-20:]
        ct_src_ltm = sum(1 for p in last_20 if p["device"] == dev["id"])
        ct_src_dport_ltm = count_in_window(lambda p: p["device"] == dev["id"] and p["dst_bucket"] == dst_bucket)
        ct_dst_sport_ltm = count_in_window(lambda p: p["dst_bucket"] == dst_bucket)
        ct_dst_src_ltm = count_in_window(lambda p: p["device"] == dev["id"] and p["proto"] == proto)
        ct_state_ttl = rng.randint(0, 3)

        recent_window.append({"device": dev["id"], "service": service, "dst_bucket": dst_bucket, "proto": proto})
        if len(recent_window) > WINDOW_SIZE:
            recent_window.pop(0)

        zone = classify(spkts, sttl)

        workload.append({
            "idx": i, "device_id": dev["id"], "device": dev["name"], "device_type": dev["type"],
            "proto": proto, "service": service, "sbytes": sbytes, "spkts": spkts,
            "smeansz": smeansz, "sttl": sttl, "swin": swin, "dst_port_bucket": dst_bucket,
            "ct_state_ttl": ct_state_ttl, "ct_srv_src": ct_srv_src, "ct_srv_dst": ct_srv_dst,
            "ct_dst_ltm": ct_dst_ltm, "ct_src_ltm": ct_src_ltm, "ct_src_dport_ltm": ct_src_dport_ltm,
            "ct_dst_sport_ltm": ct_dst_sport_ltm, "ct_dst_src_ltm": ct_dst_src_ltm,
            "zone": zone["zone"], "action_available": zone["action"],
            "r_base": zone["r_base"],
        })

    return workload


PRE_SEND_COLS = [
    "idx", "device", "proto", "service", "sbytes", "spkts", "smeansz", "sttl", "swin",
    "dst_port_bucket", "ct_state_ttl", "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm",
    "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm",
]
