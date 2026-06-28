"""
DBS_RECON_EOD_SG - End of Day Reconciliation Job
Triggered daily at 18:00 SGT
"""

import os
import sys
from datetime import datetime


def main():
    print(f"[{datetime.now()}] Starting DBS_RECON_EOD_SG job")

    # Check upstream predecessor
    predecessor = "DBS_FX_FEED_SG"
    if not check_predecessor_status(predecessor):
        print(f"ERROR: Predecessor {predecessor} not complete")
        sys.exit(1)

    # Run reconciliation
    run_reconciliation()

    print(f"[{datetime.now()}] DBS_RECON_EOD_SG completed successfully")


def check_predecessor_status(job_name):
    # Check TWS for predecessor status
    status = os.popen(f"twstask query job={job_name}").read()
    return "COMPLETE" in status


def run_reconciliation():
    # Read FX feed data
    fx_data = read_fx_feed()

    # Process reconciliation
    for record in fx_data:
        reconcile_record(record)

    print("Reconciliation complete")


def read_fx_feed():
    # Read from FX feed source
    return []


def reconcile_record(record):
    pass


if __name__ == "__main__":
    main()
