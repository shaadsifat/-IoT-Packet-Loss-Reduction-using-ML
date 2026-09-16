# IoT Packet Loss Reduction using ML

Two parts:

- **`IOT_Packet_Loss_ML_Model/`** — data pipeline and model training notebooks (01-06),
  ending in an exported Random Forest pipeline (`model/random_forest_pipeline.joblib`).
- **`IOT_Packet_Loss_Simulation/`** — Flask + JS simulation comparing no-protection,
  math-rule, and math+ML packet loss strategies. See its own README for details.

## Running the simulation

```
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python IOT_Packet_Loss_Simulation/backend/app.py
```

Open **http://localhost:5050** in a browser.

## Requirements

`requirements.txt` covers both parts: pandas, numpy, matplotlib, seaborn,
scikit-learn, xgboost, joblib (ML pipeline) and Flask (simulation backend).
