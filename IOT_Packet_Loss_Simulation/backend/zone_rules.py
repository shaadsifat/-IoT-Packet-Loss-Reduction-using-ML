"""
STEP 2 - The Stage-1 manual decision rule ("Mathematical analysis").

This is the exact 5-zone Spkts/sttl cascade validated on the real UNSW-NB15
data in IOT_Packet_Loss_ML_Model/05_manual_decision_rules.ipynb (Section 6),
with the same per-zone loss rates measured there. Nothing here is invented
for the simulation - these numbers are the notebook's output.

It is a pure, deterministic function of two pre-send values (Spkts, sttl) -
no randomness, no live state. That is intentional: it is the "manual
calculation" step, and it has to run identically every time given the same
inputs so its behaviour is auditable.
"""

ZONES = {
    1: {"action": "NO_PROTECTION", "r_base": 0.00146,
        "label": "Spkts<=4 & 30<sttl<=60"},
    2: {"action": "LIGHT", "r_base": 0.00630,
        "label": "Spkts<=4 & sttl<=30"},
    3: {"action": "MODERATE", "r_base": 0.07064,
        "label": "Spkts<=4 & sttl>60"},
    4: {"action": "MODERATE_HIGH", "r_base": 0.38508,
        "label": "Spkts>=5 & sttl<=30"},
    5: {"action": "MAX", "r_base": 0.99885,
        "label": "Spkts>=5 & sttl>30"},
}
# What each action mechanically does is a simulation-policy decision, not part
# of the validated math rule - see transmission.py's ACTION_MECHANICS.


def classify(spkts, sttl):
    """Return the zone dict a (Spkts, sttl) pair falls into."""
    if spkts <= 4:
        if 30 < sttl <= 60:
            zone = 1
        elif sttl <= 30:
            zone = 2
        else:
            zone = 3
    else:
        zone = 4 if sttl <= 30 else 5
    return {"zone": zone, **ZONES[zone]}
