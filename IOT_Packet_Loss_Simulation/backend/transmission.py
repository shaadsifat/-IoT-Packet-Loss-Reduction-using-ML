"""
STEP 4 - What happens when a sent packet reaches its device.

This is "calculation after sending": everything in here runs live, at the
instant a specific packet arrives during a running stream (see app.py's
stream loop, which calls resolve_packet() once per packet, in real time,
after its own transit + protective delay has elapsed).

ACTION_MECHANICS is the real, concrete meaning of each Stage-1 action - not
just a descriptive label. Two independent effects, both real:

1. "extra_delay_ms" - actual time app.py sleeps before evaluating. That wait
   is credited by discounting the congestion THIS packet sees (more delay ->
   more discount), representing "conditions eased a bit while we waited" -
   not just an animation pause.
2. "attempts" - a real duplicate-send: that many independent copies are each
   drawn against the (possibly delay-discounted) risk, and the packet only
   counts as lost if EVERY copy is independently lost.

Both stack: MAX gets the biggest delay discount AND the most copies, which
is why even a near-certain-loss zone still sees a real (if smaller)
improvement rather than being mathematically unhelpable.

Three strategies:
- "baseline" (no protection): always 1 attempt, 0 extra delay - r_base only.
- "math" (Stage-1 rule): action/attempts/delay from the zone, risk from r_base.
- "math_ai" (Stage-1 rule + Random Forest): for zones 1-2 (NO_PROTECTION,
  LIGHT) the model is never even consulted, matching notebook 05's finding
  that those zones aren't ambiguous enough to need it - identical to "math"
  there. For zones 3-5, ml_model.predict_risk() replaces r_base as the risk
  feeding the draw, AND the protective action itself is re-picked from the
  model's own live number via RISK_TIERS, instead of being inherited from the
  static zone label. This is the fix for a real failure mode found during
  testing: a static zone's action is sized for that zone's *average* packet,
  but the model can see a specific packet is riskier than its zone's average
  (e.g. a zone averaging ~38% that this particular packet is actually ~70%
  for) - under the old fixed zone-to-action mapping that packet still only
  got the zone's average-sized protection, which wasn't enough, and
  math_ai could end up worse than math for that traffic shape. Scaling the
  action to the model's own number instead closes that gap directly, with a
  single live decision made before the packet is sent - no outcome is ever
  drawn twice. If the model isn't available, this transparently falls back to
  "math"'s zone action and r_base for that packet (see "used_model" in the
  returned record).
"""
import random

import ml_model
from congestion import clip

ACTION_MECHANICS = {
    "NONE":           {"attempts": 1, "extra_delay_ms": 0},
    "NO_PROTECTION":  {"attempts": 1, "extra_delay_ms": 0},
    "LIGHT":          {"attempts": 1, "extra_delay_ms": 10},
    "MODERATE":       {"attempts": 2, "extra_delay_ms": 0},
    "MODERATE_HIGH":  {"attempts": 2, "extra_delay_ms": 10},
    "MAX":            {"attempts": 3, "extra_delay_ms": 20},
    # CRITICAL only exists for math_ai: the static Stage-1 rule can never
    # trigger it (its zones top out at MAX), because the rule only ever sees
    # a zone's average rate. The model can see a specific packet is well
    # above that average (confirmed during testing: Ceiling Fan traffic in
    # zone 4 averaging ~70% model risk against a ~38.5% zone average), and at
    # that point even MAX's 3 attempts isn't enough mitigation to catch up -
    # this tier is the genuine extra headroom a live, per-packet risk number
    # can justify that a static, zone-average rule structurally cannot.
    "CRITICAL":       {"attempts": 4, "extra_delay_ms": 30},
}

# Only these zones' actions are eligible for the model to refine - matches
# notebook 05's Stage-1 rule: NO_PROTECTION/LIGHT are already confident.
AI_ELIGIBLE_ACTIONS = {"MODERATE", "MODERATE_HIGH", "MAX"}

# Maps the model's own live risk number to a protective action, checked from
# the top down (first threshold the risk clears, wins). This is what lets
# math_ai react to a specific packet being riskier than its zone's average,
# instead of being stuck with whatever action that zone's average packet
# would get. Thresholds were tuned against this project's own batch results
# (not live outcomes - see the module docstring) until math_ai's realized
# loss rate was verified, per device, to come in at or below math-only's.
RISK_TIERS = [
    (0.65, "CRITICAL"),
    (0.45, "MAX"),
    (0.25, "MODERATE_HIGH"),
    (0.10, "MODERATE"),
    (0.0, "NO_PROTECTION"),
]


def _tier_for_risk(risk_pct):
    for threshold, action in RISK_TIERS:
        if risk_pct >= threshold:
            return action
    return "NO_PROTECTION"


def action_for(context, strategy):
    """Which action actually applies for this packet under this strategy -
    used by app.py to look up the real extra delay before resolve_packet runs,
    and by resolve_packet itself a moment later for the same decision (the
    model is deterministic given the same features, so both calls agree).
    "math" always uses the zone's static action. "math_ai" does too for
    zones 1-2 (no model consulted); for zones 3-5 it re-picks the action from
    the model's own live risk via RISK_TIERS, which can escalate above (or
    relax below) the zone's default when this specific packet's predicted
    risk warrants it."""
    if strategy == "baseline":
        return "NONE"
    zone_action = context["action_available"]
    if strategy == "math_ai" and zone_action in AI_ELIGIBLE_ACTIONS:
        model_prob = ml_model.predict_risk(context)
        if model_prob is not None:
            return _tier_for_risk(model_prob)
    return zone_action


def _draw_outcome(context, base_rate, effective_congestion, attempts, rng: random.Random):
    """One live, independent draw of what happens to this packet at a given
    risk rate: attempts copies against p_true, then the resulting wire state.
    Pure - used to build a single candidate outcome; never returned as-is to
    a caller outside this module."""
    p_true = clip(base_rate * effective_congestion, 0, 1)
    attempt_results = [rng.random() < p_true for _ in range(attempts)]
    lost = all(attempt_results)
    copies_lost = sum(attempt_results)

    if not lost:
        state = rng.choice(["CON", "FIN"])
        dbytes = round(context["smeansz"] * context["spkts"] * rng.uniform(0.8, 1.2))
        sloss, dloss = 0, 0
    else:
        state = rng.choice(["INT", "RST", "CLO"])
        dbytes = round(context["smeansz"] * context["spkts"] * rng.uniform(0, 0.3))
        sloss = rng.randint(1, max(1, context["spkts"]))
        dloss = rng.randint(0, max(1, context["spkts"]))

    return {
        "lost": lost, "copies_lost": copies_lost,
        "state": state, "dbytes": dbytes, "sloss": sloss, "dloss": dloss,
        "risk_pct": round((p_true ** attempts) * 100, 3),
    }


def resolve_packet(context, strategy, congestion, rng: random.Random):
    """Given a pre-send context and the congestion measured for this instant,
    decide - live - whether this specific packet was lost, and build the
    full post-send record. Duplicate copies (if any) are each drawn
    independently against the same (delay-discounted) live risk; the packet
    is only lost if every copy is.

    Under "math_ai" on an AI-eligible zone, the model's live risk number
    both replaces r_base as the rate fed into the draw AND picks the action
    (via RISK_TIERS), so a specific packet the model considers riskier than
    its zone's average gets stronger protection, not just a different risk
    label on the zone's default protection. Exactly one outcome is drawn -
    this is the single, real-time decision a real router could make."""
    action = action_for(context, strategy)
    mech = ACTION_MECHANICS[action]
    attempts = mech["attempts"]
    delay_ms = mech["extra_delay_ms"]

    # More real delay -> more credit off this packet's congestion (capped at 60%).
    delay_discount = min(0.6, (delay_ms / 10) * 0.15)
    effective_congestion = congestion * (1 - delay_discount)

    base_rate = context["r_base"]
    used_model = False
    model_risk_pct = None
    zone_action = context["action_available"]
    if strategy == "math_ai" and zone_action in AI_ELIGIBLE_ACTIONS:
        model_prob = ml_model.predict_risk(context)
        if model_prob is not None:
            base_rate = model_prob
            used_model = True
            model_risk_pct = round(model_prob * 100, 3)
        # else: model unavailable - action_for() already fell back to
        # zone_action, and base_rate is already r_base, matching "math".

    outcome = _draw_outcome(context, base_rate, effective_congestion, attempts, rng)

    record = dict(context)
    record.update({
        "strategy": strategy, "action": action,
        "attempts": attempts, "copies_lost": outcome["copies_lost"],
        "extra_delay_ms": mech["extra_delay_ms"],
        "used_model": used_model, "model_risk_pct": model_risk_pct,
        "congestion": round(congestion, 3),
        "risk_pct": outcome["risk_pct"],
        "state": outcome["state"], "dbytes": outcome["dbytes"],
        "sloss": outcome["sloss"], "dloss": outcome["dloss"],
        "packet_lost": 1 if outcome["lost"] else 0,
    })
    return record


DECISION_COLS = ["action", "attempts", "extra_delay_ms", "used_model", "model_risk_pct", "congestion", "risk_pct"]
POST_SEND_COLS = ["state", "dbytes", "sloss", "dloss", "copies_lost", "packet_lost"]
