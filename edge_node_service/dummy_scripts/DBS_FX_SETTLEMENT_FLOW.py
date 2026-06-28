#!/usr/bin/env python3
"""
DBS_FX_SETTLEMENT_FLOW.py — FX settlement processing job.

TWS JOBCMD: python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date YYYY-MM-DD --currency SGD

Dependencies (TWS job stream):
  DBS_FX_FEED_SG → DBS_FX_NETTING_CALC → DBS_FX_SETTLEMENT_FLOW

This job will NOT start if DBS_FX_NETTING_CALC is in HOLD or did not complete RC=0.
TWS error in this case: AWSBHV026E Job stream FX_SETTLEMENT not submitted

Known failure modes:
  - Predecessor DBS_FX_NETTING_CALC in HOLD → AWSBHV026E (exit code 2)
  - Predecessor cascade HOLD after upstream ABEND → same error
  - TWS plan not updated after dependency change → stream not submitted

Fix: Release HOLD on DBS_FX_NETTING_CALC via TWS console.
  conman command: release job;jb=DBS_FX_NETTING_CALC
"""

import argparse
import logging
import sys
import os
import time
from datetime import datetime

logger = logging.getLogger("DBS_FX_SETTLEMENT_FLOW")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# TWS dependency — this job requires DBS_FX_NETTING_CALC to complete first
PREDECESSOR_JOB = "DBS_FX_NETTING_CALC"
PREDECESSOR_TIMEOUT_SEC = 600

SETTLEMENT_DB_HOST = "oracle-fx-prod-01"
NETTING_OUTPUT_PATH = "hdfs://dbs-hdfs/output/fx_netting"
SETTLEMENT_OUTPUT_PATH = "hdfs://dbs-hdfs/output/fx_settlement"

CURRENCIES = ["SGD", "USD", "EUR", "HKD", "JPY", "GBP", "AUD"]


def check_predecessor_status(tws_host: str, job_name: str) -> str:
    """
    Check TWS job status via conman.
    Returns: 'COMPLETE', 'RUNNING', 'ABEND', 'HOLD', 'NOTFOUND'
    """
    try:
        import subprocess
        result = subprocess.run(
            ["conman", f"js;jb={job_name}", "-format=status"],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip().upper()
        if "COMPLETE" in output:
            return "COMPLETE"
        elif "HOLD" in output:
            return "HOLD"
        elif "ABEND" in output:
            return "ABEND"
        elif "RUNNING" in output:
            return "RUNNING"
        return "NOTFOUND"
    except Exception as e:
        logger.warning(f"Could not check predecessor status via conman: {e}")
        return "UNKNOWN"


def load_netting_results(run_date: str, currency: str) -> list:
    """Load FX netting results from HDFS output of DBS_FX_NETTING_CALC."""
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.appName("fx_settlement_loader").getOrCreate()
        path = f"{NETTING_OUTPUT_PATH}/date={run_date}/currency={currency}"
        df = spark.read.parquet(path)
        return df.collect()
    except Exception as e:
        logger.error(f"Failed to load netting results: {e}")
        return []


def process_settlements(netting_records: list, run_date: str, currency: str) -> dict:
    """Process settlement instructions from netting results."""
    settlements = {"gross": 0.0, "net": 0.0, "count": len(netting_records)}
    for record in netting_records:
        settlements["gross"] += getattr(record, "gross_amount", 0.0)
        settlements["net"] += getattr(record, "net_amount", 0.0)
    logger.info(f"Settlement {currency}: gross={settlements['gross']:.2f} net={settlements['net']:.2f} n={settlements['count']}")
    return settlements


def run_settlement(run_date: str, currency: str):
    logger.info(f"Starting FX settlement processing: date={run_date} currency={currency}")

    # Check predecessor status (informational — TWS enforces the hard dependency)
    # If this job is running, TWS has already confirmed predecessor completed RC=0
    # But if predecessor was manually re-submitted and this job was force-started,
    # we verify here as a safety check.
    logger.info(f"Checking predecessor {PREDECESSOR_JOB} status")
    status = check_predecessor_status("tws-prod-01", PREDECESSOR_JOB)

    if status == "HOLD":
        logger.error(f"Predecessor {PREDECESSOR_JOB} is in HOLD state")
        logger.error(f"Resolution: Release HOLD via TWS console: conman 'release job;jb={PREDECESSOR_JOB}'")
        logger.error("AWSBHV026E Job stream FX_SETTLEMENT not submitted — predecessor did not complete successfully")
        sys.exit(2)
    elif status == "ABEND":
        logger.error(f"Predecessor {PREDECESSOR_JOB} ABEND — cannot proceed with settlement")
        sys.exit(2)
    elif status in ("COMPLETE", "UNKNOWN"):
        logger.info(f"Predecessor status: {status} — proceeding with settlement")

    # Load netting results
    logger.info(f"Loading netting results for {run_date} {currency}")
    netting_records = load_netting_results(run_date, currency)

    if not netting_records:
        logger.warning(f"No netting records found for {run_date} {currency}")
        sys.exit(0)

    # Process settlements
    settlements = process_settlements(netting_records, run_date, currency)

    # Write settlement output
    output_path = f"{SETTLEMENT_OUTPUT_PATH}/date={run_date}/currency={currency}"
    logger.info(f"Writing settlement output to {output_path}")

    # Simulate output write
    logger.info(f"FX settlement complete: {currency} gross={settlements['gross']:.2f} net={settlements['net']:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Settlement date YYYY-MM-DD")
    parser.add_argument("--currency", default="SGD", choices=CURRENCIES)
    args = parser.parse_args()

    run_settlement(args.date, args.currency)
