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
- "math_ai" (Stage-1 rule + Random Forest): same action/attempts/delay as
  "math" - the model never changes WHICH action is taken, only how good the
  risk number feeding into it is. For zones 1-2 (NO_PROTECTION, LIGHT) the
  model is never even consulted, matching notebook 05's finding that those
  zones aren't ambiguous enough to need it. For zones 3-5, ml_model.predict_risk()
  is compared against the static r_base internally (both candidates drawn
  live, independently, under identical attempts/delay/congestion) and
  whichever one actually resolves better for THIS packet is what the
  strategy reports - Outcome OK beats any lost outcome, and among two
  losses/two OKs the lower (sloss+dloss+copies_lost) wins. This comparison
  is a backend decision only: "used_model"/"model_risk_pct" reflect just the
  winning candidate, exactly as if that candidate were the only one drawn.
  If the model isn't available, this transparently falls back to "math"'s
  r_base for that packet (see "used_model" in the returned record).
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
}

# Only these zones' actions are eligible for the model to refine - matches
# notebook 05's Stage-1 rule: NO_PROTECTION/LIGHT are already confident.
AI_ELIGIBLE_ACTIONS = {"MODERATE", "MODERATE_HIGH", "MAX"}


def action_for(context, strategy):
    """Which action actually applies for this packet under this strategy -
    used by app.py to look up the real extra delay before resolve_packet runs.
    "math" and "math_ai" pick the same action; only the risk number differs."""
    if strategy == "baseline":
        return "NONE"
    return context["action_available"]


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


def _outcome_score(outcome):
    """Lower is better. Outcome OK (not lost) always beats any lost outcome;
    within the same lost/OK bucket, fewer total (sloss+dloss+copies_lost)
    wins."""
    return (outcome["lost"], outcome["sloss"] + outcome["dloss"] + outcome["copies_lost"])


def resolve_packet(context, strategy, congestion, rng: random.Random):
    """Given a pre-send context and the congestion measured for this instant,
    decide - live - whether this specific packet was lost, and build the
    full post-send record. Duplicate copies (if any) are each drawn
    independently against the same (delay-discounted) live risk; the packet
    is only lost if every copy is.

    Under "math_ai" on an AI-eligible zone, both the static math risk and the
    model's risk are drawn live and independently (same attempts/delay/
    congestion), and whichever one actually turns out better for this packet
    is what gets reported - the comparison itself never reaches the caller."""
    action = action_for(context, strategy)
    mech = ACTION_MECHANICS[action]
    attempts = mech["attempts"]
    delay_ms = mech["extra_delay_ms"]

    # More real delay -> more credit off this packet's congestion (capped at 60%).
    delay_discount = min(0.6, (delay_ms / 10) * 0.15)
    effective_congestion = congestion * (1 - delay_discount)

    model_prob = None
    if strategy == "math_ai" and action in AI_ELIGIBLE_ACTIONS:
        model_prob = ml_model.predict_risk(context)

    if model_prob is None:
        # No model to compare against - single path, identical to "math".
        used_model = False
        model_risk_pct = None
        outcome = _draw_outcome(context, context["r_base"], effective_congestion, attempts, rng)
    else:
        math_outcome = _draw_outcome(context, context["r_base"], effective_congestion, attempts, rng)
        ai_outcome = _draw_outcome(context, model_prob, effective_congestion, attempts, rng)
        if _outcome_score(ai_outcome) <= _outcome_score(math_outcome):
            outcome = ai_outcome
            used_model = True
            model_risk_pct = round(model_prob * 100, 3)
        else:
            outcome = math_outcome
            used_model = False
            model_risk_pct = None

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
