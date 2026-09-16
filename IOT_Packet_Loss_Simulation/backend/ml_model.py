"""
STEP 2b - The trained Random Forest, loaded once at server startup.

Only consulted for zones 3-5 (MODERATE, MODERATE_HIGH, MAX) under the
"math_ai" strategy - zones 1-2 stay pure math always (see zone_rules.py),
by design: notebook 05 found no genuine ambiguity for Spkts<=4 that would
justify handing off to a model.

The exported artifact (model/random_forest_pipeline.joblib) is the exact
model evaluated in IOT_Packet_Loss_ML_Model/04_model_training_and_evaluation
and packaged for deployment in .../06_export_deployment_model.ipynb - same
10 features, same split, same hyperparameters, nothing retrained here.

If the file is missing or fails to load, every caller gets None back and
is expected to fall back to the same static r_base math Strategy B already
uses - the simulation never crashes or blocks on a missing model file.
"""
import json
import os

import joblib
import pandas as pd

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
MODEL_PATH = os.path.join(MODEL_DIR, "random_forest_pipeline.joblib")
INFO_PATH = os.path.join(MODEL_DIR, "model_info.json")

_pipeline = None
_feature_cols = None
_info = None
_load_attempted = False
_load_error = None


def _load():
    global _pipeline, _feature_cols, _info, _load_attempted, _load_error
    if _load_attempted:
        return
    _load_attempted = True
    try:
        _pipeline = joblib.load(MODEL_PATH)
        # The model was trained with n_jobs=-1 (fastest for bulk training/eval),
        # but that spins up a worker pool on EVERY call - ruinous for the
        # one-row-at-a-time inference this simulation actually does (~29ms/call
        # vs ~12ms/call, measured). n_jobs=1 is strictly better here; it changes
        # nothing about what the model predicts, only how it's scheduled.
        classifier = _pipeline.named_steps.get("classifier")
        if classifier is not None and hasattr(classifier, "n_jobs"):
            classifier.n_jobs = 1
        with open(INFO_PATH, "r", encoding="utf-8") as f:
            _info = json.load(f)
        _feature_cols = _info["feature_columns"]
        print(f"[ml_model] loaded {MODEL_PATH} (test accuracy {_info.get('test_accuracy_pct')}%)")
    except Exception as exc:  # missing file, bad joblib, whatever - degrade, don't crash
        _load_error = str(exc)
        print(f"[ml_model] could not load model, falling back to math-only: {_load_error}")


def is_available():
    _load()
    return _pipeline is not None


def load_error():
    _load()
    return _load_error


def info():
    _load()
    return _info


def predict_risk(context):
    """Returns a probability in [0,1] the trained model assigns to this
    packet, using only its pre-send feature values - or None if the model
    isn't available. Callers must fall back to r_base themselves on None."""
    _load()
    if _pipeline is None:
        return None
    row = pd.DataFrame([{col: context[col] for col in _feature_cols}])
    return float(_pipeline.predict_proba(row)[0][1])
