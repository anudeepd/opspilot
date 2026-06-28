#!/usr/bin/env python3
"""
DBS_CREDIT_SCORE_CALC.py — Daily credit score recalculation batch job.

TWS JOBCMD: /usr/bin/python /jobs/DBS_CREDIT_SCORE_CALC.py --date YYYY-MM-DD
  ^ KNOWN ISSUE: /usr/bin/python = Python 2.7 on many hosts.
    This script requires Python 3.8+ (walrus operator, f-strings, sklearn).
    Fix: Update JOBCMD to /usr/bin/python3

    Also requires: source /opt/venvs/credit/bin/activate
    Otherwise: ModuleNotFoundError: No module named 'sklearn'

Fix applied (INC-20241030-D001):
  - JOBCMD updated from /usr/bin/python to /usr/bin/python3
  - JOBCMD now activates venv: source /opt/venvs/credit/bin/activate && python3 ...
"""

import argparse
import logging
import sys
import os

logger = logging.getLogger("DBS_CREDIT_SCORE_CALC")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Requires Python 3.6+ for f-strings, Python 3.8+ for walrus operator, scikit-learn
try:
    import pandas as pd
    from sklearn.preprocessing import StandardScaler   # line 18 — ModuleNotFoundError if no venv
    from sklearn.ensemble import GradientBoostingClassifier
except ImportError as e:
    logger.error(f"Import error: {e}")
    logger.error("Ensure virtualenv is activated: source /opt/venvs/credit/bin/activate")
    sys.exit(1)

DB_HOST = "mariadb-prod-01"
DB_NAME = "credit_db"
MODEL_PATH = "/opt/models/credit_score_v3.pkl"
OUTPUT_TABLE = "credit_scores_daily"

RISK_THRESHOLDS = {
    "low":    (0.0, 0.30),
    "medium": (0.30, 0.65),
    "high":   (0.65, 1.0),
}


def fetch_customers(cursor, calc_date: str):
    cursor.execute(
        "SELECT customer_id, annual_income, debt_ratio, payment_history, "
        "       num_accounts, credit_utilisation "
        "FROM customers WHERE last_score_date < %s OR last_score_date IS NULL",
        (calc_date,)
    )
    return cursor.fetchall()


def calculate_risk_band(score: float) -> str:
    for band, (low, high) in RISK_THRESHOLDS.items():
        if low <= score < high:
            return band
    return "high"


def process_customer_scores(customers, scaler, model):
    results = []
    # Python 3.8+ walrus operator — line 51
    # KNOWN ISSUE: SyntaxError: invalid syntax under Python < 3.8
    while chunk := customers[:CHUNK_SIZE]:  # noqa: E999 — requires Python 3.8
        customers = customers[CHUNK_SIZE:]
        df = pd.DataFrame(chunk, columns=[
            "customer_id", "annual_income", "debt_ratio",
            "payment_history", "num_accounts", "credit_utilisation"
        ])
        features = df.drop("customer_id", axis=1)
        scaled = scaler.transform(features)
        scores = model.predict_proba(scaled)[:, 1]

        for cust_id, score in zip(df["customer_id"], scores):
            risk_band = calculate_risk_band(float(score))
            # f-string — requires Python 3.6+
            logger.debug(f"Customer {cust_id}: score={score:.4f} band={risk_band}")
            results.append((cust_id, float(score), risk_band))

    return results


CHUNK_SIZE = 1000


def run_credit_score_calc(calc_date: str):
    try:
        import mysql.connector
        import pickle
    except ImportError as e:
        logger.error(f"Dependency missing: {e}")
        sys.exit(1)

    logger.info(f"Loading credit score model from {MODEL_PATH}")
    try:
        with open(MODEL_PATH, "rb") as f:
            model_data = pickle.load(f)
        scaler = model_data["scaler"]
        model = model_data["model"]
    except FileNotFoundError:
        logger.error(f"Model file not found: {MODEL_PATH}")
        sys.exit(1)

    logger.info(f"Connecting to {DB_HOST}/{DB_NAME}")
    conn = mysql.connector.connect(
        host=DB_HOST, database=DB_NAME, user="credit_svc", password="REDACTED"
    )
    cursor = conn.cursor()

    try:
        customers = fetch_customers(cursor, calc_date)
        logger.info(f"Processing {len(customers)} customers for date {calc_date}")

        results = process_customer_scores(list(customers), scaler, model)

        logger.info(f"Updating {len(results)} credit scores in {OUTPUT_TABLE}")
        cursor.executemany(
            f"INSERT INTO {OUTPUT_TABLE} (customer_id, score, risk_band, calc_date) "
            "VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE score=%s, risk_band=%s",
            [(cid, sc, rb, calc_date, sc, rb) for cid, sc, rb in results]
        )
        conn.commit()
        logger.info(f"Credit score calculation complete for {calc_date}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Calculation date YYYY-MM-DD")
    args = parser.parse_args()

    run_credit_score_calc(args.date)
