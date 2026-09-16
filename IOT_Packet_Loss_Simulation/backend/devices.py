"""
STEP 0 - The network topology.

One router, seven receiving IoT devices. Every device's profile below is a
deliberate choice grounded in how that class of device actually talks on a
real home network - not arbitrary numbers:

- Light Bulbs / Ceiling Fans: cheap embedded Wi-Fi MCUs (ESP8266/ESP32-class
  chips). They almost always speak UDP for status/control traffic (no TCP
  handshake overhead needed for "turn on" / "set speed 2") and ship with
  low, close-together default TTLs because their network stack is a small,
  fixed-configuration RTOS image, not a general-purpose OS - reflected here
  as a narrow sttl_jit band low in the range.
- AC Unit / Heater: heavier appliances that run fuller embedded Linux/RTOS
  stacks with more elaborate control panels (scheduling, diagnostics,
  firmware updates), which is why they're modeled on TCP with an HTTP/DNS-
  style service and a higher, more Linux-like default TTL.

None of this is used to fabricate a loss outcome - it only shapes the
Spkts/sttl values each device tends to produce, which is exactly the kind
of thing a real router would observe about its own traffic before sending.
"""

DEVICES = [
    {"id": "lb1", "name": "Light Bulb 1", "type": "Light Bulb", "sttl_base": 45, "sttl_jit": 10,
     "proto": "udp", "service": "none", "dst_bucket": "registered"},
    {"id": "lb2", "name": "Light Bulb 2", "type": "Light Bulb", "sttl_base": 45, "sttl_jit": 10,
     "proto": "udp", "service": "none", "dst_bucket": "registered"},
    {"id": "lb3", "name": "Light Bulb 3", "type": "Light Bulb", "sttl_base": 45, "sttl_jit": 10,
     "proto": "udp", "service": "none", "dst_bucket": "registered"},
    {"id": "cf1", "name": "Ceiling Fan 1", "type": "Ceiling Fan", "sttl_base": 20, "sttl_jit": 8,
     "proto": "udp", "service": "none", "dst_bucket": "registered"},
    {"id": "cf2", "name": "Ceiling Fan 2", "type": "Ceiling Fan", "sttl_base": 20, "sttl_jit": 8,
     "proto": "udp", "service": "none", "dst_bucket": "registered"},
    {"id": "ac1", "name": "AC Unit", "type": "Air Conditioner", "sttl_base": 128, "sttl_jit": 20,
     "proto": "tcp", "service": "dns", "dst_bucket": "well_known"},
    {"id": "ht1", "name": "Heater", "type": "Heater", "sttl_base": 200, "sttl_jit": 30,
     "proto": "tcp", "service": "http", "dst_bucket": "well_known"},
]


def fresh_device_state():
    """A new, independent send-session counter for every device (Step 1 uses this)."""
    return {d["id"]: {"spkts": 1, "session_len": None} for d in DEVICES}
