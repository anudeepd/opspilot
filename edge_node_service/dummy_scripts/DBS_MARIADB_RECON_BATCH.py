#!/usr/bin/env python3
"""
DBS_MARIADB_RECON_BATCH.py — End-of-day reconciliation job against MariaDB recon_db.

TWS JOBCMD: python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date YYYY-MM-DD --mode full

Known issues (pre-fix):
  - No index on account_id column in trades table → full table scan per iteration
  - Per-row INSERT loop instead of executemany() → 85,000 individual transactions
  - New DB connection opened per batch iteration → connection pool exhaustion

Fix applied (INC-20241104-A001):
  - Added composite index: trades(account_id, trade_date)
  - Rewrote INSERT to use cursor.executemany()
  - Single persistent connection for entire job
"""

import argparse
import logging
import sys
from datetime import datetime, date

logger = logging.getLogger("DBS_MARIADB_RECON_BATCH")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_HOST = "mariadb-prod-01"
DB_PORT = 3306
DB_NAME = "recon_db"
DB_USER = "recon_svc"
DB_PASS = "REDACTED"

BATCH_SIZE = 500


def get_account_list(cursor, recon_date: str):
    """Fetch list of accounts requiring reconciliation on this date."""
    cursor.execute(
        "SELECT DISTINCT account_id FROM trade_schedule WHERE sched_date = %s AND status = 'PENDING'",
        (recon_date,)
    )
    return [row[0] for row in cursor.fetchall()]


def fetch_trades_for_account(cursor, account_id: str, recon_date: str):
    """
    KNOWN ISSUE (pre-fix): Full table scan — no index on account_id.
    SELECT * causes full scan of 12M row trades table per account_id.
    Fix: CREATE INDEX idx_trades_account_date ON trades(account_id, trade_date)
    """
    cursor.execute(
        "SELECT trade_id, account_id, trade_date, amount, status "
        "FROM trades WHERE account_id = %s AND trade_date = %s",
        (account_id, recon_date)
    )
    return cursor.fetchall()


def insert_recon_records(cursor, records):
    """
    KNOWN ISSUE (pre-fix): Single-row INSERT in loop — 85,000 individual transactions.
    Fix: Use cursor.executemany() with single commit at end.
    """
    # Pre-fix code (anti-pattern):
    # for rec in records:
    #     cursor.execute("INSERT INTO recon_results VALUES (%s, %s, %s, %s, %s)", rec)
    #     conn.commit()  # 85,000 individual commits — kills InnoDB redo log

    # Fixed code: batch insert
    cursor.executemany(
        "INSERT INTO recon_results (trade_id, account_id, recon_date, amount, recon_status) "
        "VALUES (%s, %s, %s, %s, %s)",
        records
    )


def run_reconciliation(recon_date: str, mode: str):
    try:
        import mysql.connector
    except ImportError:
        logger.error("mysql-connector-python not installed. Run: pip3 install mysql-connector-python")
        sys.exit(1)

    logger.info(f"Connecting to {DB_HOST}:{DB_PORT}/{DB_NAME}")

    # Fixed: single connection for entire job (not per-iteration)
    conn = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS,
        connection_timeout=30,
    )
    cursor = conn.cursor()

    try:
        accounts = get_account_list(cursor, recon_date)
        logger.info(f"Processing {len(accounts)} accounts for date {recon_date}")

        all_records = []
        for account_id in accounts:
            trades = fetch_trades_for_account(cursor, account_id, recon_date)
            for trade in trades:
                recon_rec = (trade[0], trade[1], recon_date, trade[3], "RECONCILED")
                all_records.append(recon_rec)

        logger.info(f"Inserting {len(all_records)} reconciliation records")
        insert_recon_records(cursor, all_records)
        conn.commit()
        logger.info(f"Reconciliation complete for {recon_date}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Reconciliation date YYYY-MM-DD")
    parser.add_argument("--mode", default="full", choices=["full", "incremental"])
    args = parser.parse_args()

    run_reconciliation(args.date, args.mode)
