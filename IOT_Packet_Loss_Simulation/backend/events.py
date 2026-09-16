"""
STEP 6 (wiring) - formats the two live events the frontend listens for.

Kept separate from app.py on purpose: this file has no simulation logic in
it at all, it only knows how to shape a Python dict into a Server-Sent
Event line. That separation is what makes app.py readable as "the order
things happen in" rather than a mix of streaming plumbing and simulation
rules.
"""
import json


def sse(event_name, payload):
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def sent_event(context):
    """Packet has left the router - only pre-send information exists yet."""
    from workload import PRE_SEND_COLS
    payload = {k: context[k] for k in PRE_SEND_COLS if k in context}
    payload["device_id"] = context["device_id"]
    return sse("sent", payload)


def landed_event(record):
    """Packet has resolved - the live decision + outcome now exist."""
    return sse("landed", record)


def meta_event(total):
    return sse("meta", {"total": total})


def done_event():
    return sse("done", {})
