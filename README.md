# IoT Packet Loss Reduction using ML

Thesis project: predicting IoT network packet-loss risk from network traffic data, so mitigation actions (retransmit, reroute, reprioritize) could be triggered before loss actually happens.

This repository currently covers Part 1 of the project: preparing the dataset and selecting/testing a classification model. Part 2 (a simulation testbed that uses the model's predictions to trigger mitigation and measure loss-rate reduction) is not part of this repository yet.

## Dataset

**TON_IoT - `Train_Test_Network.csv`** (UNSW Canberra Cyber), downloaded from Kaggle.

This dataset was originally built for network intrusion detection, not packet loss, so it does not ship with a "packet lost" label - that label is derived here from the `missed_bytes` column (`packet_lost = 1 if missed_bytes > 0 else 0`). It was chosen over other IoT security datasets (Edge-IIoTset, IoT-23) because its column schema is an exact match for the Zeek-style network log fields this project needed (`missed_bytes`, `conn_state`, `src_pkts`/`dst_pkts`, etc.), it is a manageable size (~211k rows), and it is well documented and widely used in IoT network security research.

Known limitation: this export has no timestamp column and no RSSI/signal-strength data, so true time-windowed congestion features and burstiness modeling (LSTM/GRU) are not possible from this source. A connection-count-per-source-IP feature is used as the closest available proxy for congestion.

## Project structure

```
train_test_network.csv                          Raw dataset from Kaggle (read-only, never modified)
network_data_columns_selected.csv                Raw data with irrelevant columns removed (211,043 rows x 16 cols)
network_data_cleaned_features.csv                Final cleaned + feature-engineered dataset (190,474 rows x 24 cols)

01_data_cleaning_and_feature_engineering.ipynb   Column selection, deduplication, missing-value handling, feature engineering
02_model_selection_analysis.ipynb                Exploratory analysis used to choose a model family
03_baseline_model_accuracy.ipynb                 Baseline accuracy comparison across 4 candidate models

requirements.txt                                 Python package versions used
```

## What has been done

**01 - Data cleaning and feature engineering**
Starting from the raw 44-column export, 28 sparse/protocol-specific columns (DNS, SSL, HTTP, Zeek "weird" flags, source port) were dropped, since they were over 60-100% empty and not relevant to network-layer loss. Exact duplicate rows (20,569 of them) were removed, using the full original record to decide what counts as a duplicate so that repeated scanning/DDoS attack traffic was not mistakenly deleted. Eight new columns were engineered on top of the cleaned data, including the derived target `packet_lost`, traffic totals, an incomplete-connection flag, a connection-count-per-source-IP congestion proxy, and a destination-port category.

**02 - Model selection analysis**
Before committing to any model, the cleaned dataset was examined for what actually determines model choice: severe class imbalance (about 1.55% of rows are positive), heavily right-skewed numeric features with class-correlated outliers, redundant/correlated engineered features, and a lack of linear separability between the two classes (checked via PCA). A head-to-head comparison of four candidate models on a held-out test split confirmed the reasoning: Random Forest and XGBoost both reached about 0.986-0.987 PR-AUC, compared to 0.235 for Logistic Regression.

**03 - Baseline model accuracy**
The same four models (Logistic Regression, Decision Tree, Random Forest, XGBoost) were trained on an 80/20 stratified split and compared on accuracy only, as an initial baseline pass:

| Model | Accuracy |
|---|---|
| Logistic Regression | 0.9434 |
| Decision Tree | 0.9902 |
| Random Forest | 0.9983 |
| XGBoost | 0.9982 |

Because only about 1.55% of rows are positive, accuracy alone is not a reliable measure of how well a model actually detects loss events - a model predicting "no loss" every time would already score about 98.45%. A full evaluation with precision, recall, F1, and a confusion matrix is planned as a follow-up step, along with hyperparameter tuning for Random Forest and XGBoost.

## Tools and libraries used

- Python 3.12
- Jupyter Notebook
- pandas, numpy - data loading and manipulation
- matplotlib, seaborn - visualization
- scikit-learn - preprocessing, train/test splitting, Logistic Regression, Decision Tree, Random Forest, evaluation metrics
- XGBoost - gradient-boosted tree classifier

Exact package versions are pinned in `requirements.txt`.

## How to run

1. Install Python 3.12 or later.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Launch Jupyter from this folder:
   ```
   jupyter notebook
   ```
4. Run the notebooks in order: `01_data_cleaning_and_feature_engineering.ipynb`, then `02_model_selection_analysis.ipynb`, then `03_baseline_model_accuracy.ipynb`. Each notebook can be re-run end-to-end (Kernel > Restart & Run All) and will regenerate its own output file(s) without needing any manual steps in between.

## Next steps

- Full evaluation of Random Forest and XGBoost: confusion matrix, precision, recall, F1-score.
- Hyperparameter tuning for both models.
- Write up final model performance results for the thesis.

## Git Repo

https://github.com/shaadsifat/IoT-Packet-Loss-Reduction-using-ML.git
