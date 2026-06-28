"""
Create and populate the ChromaDB vector store from a rich dummy iChamp dataset.

Usage:
  python scripts/create_vector_db.py            # build normally
  python scripts/create_vector_db.py --recreate # clear existing collection first
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaml
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)


def create_dummy_excel():
    """Create rich iChamp tickets Excel with 32 tickets across 6 failure scenarios."""

    # ── Scenario A: MariaDB CPU Spike ────────────────────────────────────────
    scenario_a = [
        {
            "INCIDENT_ID": "INC-20241104-A001",
            "JOB_NAME": "DBS_MARIADB_RECON_BATCH",
            "SCRIPT_NAME": "DBS_MARIADB_RECON_BATCH.py",
            "COMMAND": "python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date 2024-11-04 --mode full",
            "SUMMARY": "MariaDB batch reconciliation job CPU spike 96% — ABEND wallclock exceeded",
            "INCIDENT_DETAILS": (
                "DBS_MARIADB_RECON_BATCH terminated after exceeding its 1200s wallclock limit. "
                "DBA alert showed mariadb-prod-01 CPU at 96% for 18 minutes during the job window. "
                "Slow query log showed SELECT * FROM trades WHERE account_id=? executing full table scans. "
                "No index on account_id column in the trades table. Job failed with exit code 134."
            ),
            "RESOLUTION": (
                "Added composite index on trades(account_id, trade_date). "
                "Rewrote bulk INSERT loop to use executemany() — reduced DB round-trips from 8400 to 42. "
                "Job re-ran in 8 minutes. CPU peaked at 22%. Closed."
            ),
            "ROOT_CAUSE": "Missing index on account_id — full table scan per iteration",
            "RESOLUTION_CODE": "RC-DB-IDX",
            "APPLICATION_CODE": "DBS-BATCH",
            "FAILURE_TYPE": "cpu_high",
            "RESOLVED_BY": "John Tan",
            "RESOLVED_DATE": "2024-11-04",
            "MTTD": 18, "MTTR": 45,
        },
        {
            "INCIDENT_ID": "INC-20241018-A002",
            "JOB_NAME": "DBS_MARIADB_RECON_BATCH",
            "SCRIPT_NAME": "DBS_MARIADB_RECON_BATCH.py",
            "COMMAND": "python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date 2024-10-18 --mode full",
            "SUMMARY": "Batch job runaway full-table scan causing DB CPU overload",
            "INCIDENT_DETAILS": (
                "Job running for over 25 minutes against MariaDB recon_db.trades table. "
                "DBA reported 98% CPU on DB host. Query plan shows full table scan on 12M row table. "
                "EXPLAIN output: type=ALL, rows=12048321, filtered=1.23%. Job ABEND RC=134."
            ),
            "RESOLUTION": (
                "Emergency: killed the runaway query session. "
                "Identified N+1 query pattern — script queried account status inside a loop per trade. "
                "Rewrote to batch-fetch account status in single query before loop. "
                "Added index. Job re-ran in 6 minutes."
            ),
            "ROOT_CAUSE": "N+1 query pattern with full-table scan inside tight loop",
            "RESOLUTION_CODE": "RC-DB-QUERY",
            "APPLICATION_CODE": "DBS-BATCH",
            "FAILURE_TYPE": "cpu_high",
            "RESOLVED_BY": "Alice Lim",
            "RESOLVED_DATE": "2024-10-18",
            "MTTD": 25, "MTTR": 60,
        },
        {
            "INCIDENT_ID": "INC-20240922-A003",
            "JOB_NAME": "DBS_MARIADB_RECON_BATCH",
            "SCRIPT_NAME": "DBS_MARIADB_RECON_BATCH.py",
            "COMMAND": "python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date 2024-09-22 --mode full",
            "SUMMARY": "DB connection pool exhaustion causing batch job stall and CPU spike",
            "INCIDENT_DETAILS": (
                "Job opened 420 separate MySQL connections (one per batch iteration, no pooling). "
                "MariaDB max_connections=200 — connections queued and timed out. "
                "CPU spiked handling connection overhead. Job eventually ABEND after 1800s."
            ),
            "RESOLUTION": (
                "Replaced per-iteration connection.connect() with a single connection opened before the loop. "
                "Alternatively implemented mysql-connector-python pooling with pool_size=5. "
                "Job now uses 1 persistent connection. Runtime dropped from 30m+ to 4m."
            ),
            "ROOT_CAUSE": "No connection pooling — new DB connection opened per batch row",
            "RESOLUTION_CODE": "RC-DB-POOL",
            "APPLICATION_CODE": "DBS-BATCH",
            "FAILURE_TYPE": "cpu_high",
            "RESOLVED_BY": "David Lee",
            "RESOLVED_DATE": "2024-09-22",
            "MTTD": 30, "MTTR": 90,
        },
        {
            "INCIDENT_ID": "INC-20240808-A004",
            "JOB_NAME": "DBS_MARIADB_RECON_BATCH",
            "SCRIPT_NAME": "DBS_MARIADB_RECON_BATCH.py",
            "COMMAND": "python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date 2024-08-08 --mode full",
            "SUMMARY": "Unoptimised bulk INSERT driving DB host to 95% CPU",
            "INCIDENT_DETAILS": (
                "Script inserting 85,000 reconciliation records using single-row INSERT in for-loop. "
                "Each iteration committed separately — 85,000 individual transactions. "
                "InnoDB transaction log fill rate caused secondary CPU spike. Job ABEND RC=134."
            ),
            "RESOLUTION": (
                "Changed INSERT loop to accumulate records in list, then call cursor.executemany(). "
                "Wrapped in single transaction with explicit commit at end. "
                "Insertion time: 4200s → 12s. CPU peak: 95% → 18%."
            ),
            "ROOT_CAUSE": "Single-row INSERT in loop instead of executemany() batch insert",
            "RESOLUTION_CODE": "RC-DB-BULK",
            "APPLICATION_CODE": "DBS-BATCH",
            "FAILURE_TYPE": "cpu_high",
            "RESOLVED_BY": "Sarah Wong",
            "RESOLVED_DATE": "2024-08-08",
            "MTTD": 12, "MTTR": 55,
        },
        {
            "INCIDENT_ID": "INC-20240715-A005",
            "JOB_NAME": "DBS_MARIADB_RECON_BATCH",
            "SCRIPT_NAME": "DBS_MARIADB_RECON_BATCH.py",
            "COMMAND": "python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date 2024-07-15 --mode full",
            "SUMMARY": "Missing index on trade_date — month-end recon CPU overload",
            "INCIDENT_DETAILS": (
                "Month-end run. Query includes WHERE trade_date BETWEEN '2024-07-01' AND '2024-07-15'. "
                "No index on trade_date column. Full scan of 14M rows per date-range query. "
                "18 date ranges queried in sequence — 18 full scans. CPU: 97%. Wallclock ABEND."
            ),
            "RESOLUTION": (
                "Added index on trades(trade_date). Verified with EXPLAIN — type changed from ALL to range. "
                "Added composite index trades(account_id, trade_date) for combined filter queries. "
                "Month-end rerun completed in 11 minutes."
            ),
            "ROOT_CAUSE": "Missing index on trade_date column — 18 full-table scans in sequence",
            "RESOLUTION_CODE": "RC-DB-IDX",
            "APPLICATION_CODE": "DBS-BATCH",
            "FAILURE_TYPE": "cpu_high",
            "RESOLVED_BY": "Mike Chen",
            "RESOLVED_DATE": "2024-07-15",
            "MTTD": 20, "MTTR": 35,
        },
        {
            "INCIDENT_ID": "INC-20240610-A006",
            "JOB_NAME": "DBS_MARIADB_RECON_BATCH",
            "SCRIPT_NAME": "DBS_MARIADB_RECON_BATCH.py",
            "COMMAND": "python3 /jobs/DBS_MARIADB_RECON_BATCH.py --date 2024-06-10 --mode full",
            "SUMMARY": "MariaDB CPU high — excessive DELETE + re-INSERT pattern instead of UPDATE",
            "INCIDENT_DETAILS": (
                "Script logic: for each reconciliation record, DELETE existing row then INSERT new version. "
                "This triggered full index rebuild on every change — 42,000 DELETE+INSERT pairs. "
                "InnoDB fragmentation and CPU overhead from redo log writes. CPU: 93%."
            ),
            "RESOLUTION": (
                "Replaced DELETE+INSERT pattern with INSERT ... ON DUPLICATE KEY UPDATE. "
                "Reduced index churn by 90%. CPU dropped to 15% on next run. "
                "Dev team updated script template to use upsert pattern going forward."
            ),
            "ROOT_CAUSE": "DELETE+INSERT pattern instead of upsert causing index rebuild overhead",
            "RESOLUTION_CODE": "RC-DB-QUERY",
            "APPLICATION_CODE": "DBS-BATCH",
            "FAILURE_TYPE": "cpu_high",
            "RESOLVED_BY": "Emma Chen",
            "RESOLVED_DATE": "2024-06-10",
            "MTTD": 15, "MTTR": 40,
        },
    ]

    # ── Scenario B: Spark OOM / Executor Failure ──────────────────────────────
    scenario_b = [
        {
            "INCIDENT_ID": "INC-20241103-B001",
            "JOB_NAME": "DBS_SPARK_RISK_AGGREGATION",
            "SCRIPT_NAME": "DBS_SPARK_RISK_AGGREGATION.py",
            "COMMAND": "spark-submit --master yarn --deploy-mode cluster /jobs/DBS_SPARK_RISK_AGGREGATION.py --date 2024-11-03",
            "SUMMARY": "Spark risk aggregation ABEND — executors lost with OutOfMemoryError during join",
            "INCIDENT_DETAILS": (
                "PySpark job submitted via spark-submit on YARN cluster. "
                "Stage 4 (join at DBS_SPARK_RISK_AGGREGATION.py:87) failed with FetchFailedException. "
                "Executors 3 and 5 lost: java.lang.OutOfMemoryError: GC overhead limit exceeded. "
                "spark.executor.memory not set — defaulting to 1g. "
                "Join between positions_df (2.1GB) and risk_factors_df (800MB) without repartition."
            ),
            "RESOLUTION": (
                "Set spark.executor.memory=6g and spark.executor.cores=4 in spark-submit. "
                "Added df.repartition(200) before the join operation. "
                "Replaced df.collect() with df.write.parquet() for large result set. "
                "Job completed in 14 minutes on next run. All executors stable."
            ),
            "ROOT_CAUSE": "Insufficient executor memory (default 1g) and missing repartition before large join",
            "RESOLUTION_CODE": "RC-SPARK-MEM",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "oom",
            "RESOLVED_BY": "Bob Tan",
            "RESOLVED_DATE": "2024-11-03",
            "MTTD": 10, "MTTR": 45,
        },
        {
            "INCIDENT_ID": "INC-20241020-B002",
            "JOB_NAME": "DBS_SPARK_RISK_AGGREGATION",
            "SCRIPT_NAME": "DBS_SPARK_RISK_AGGREGATION.py",
            "COMMAND": "spark-submit --master yarn --deploy-mode cluster /jobs/DBS_SPARK_RISK_AGGREGATION.py --date 2024-10-20",
            "SUMMARY": "Skewed partition causing single executor OOM on Spark risk job",
            "INCIDENT_DETAILS": (
                "Executor 7 lost: java.lang.OutOfMemoryError: Java heap space. "
                "Others executors idle while executor 7 processed 78% of data. "
                "GroupBy on currency_code — SGD bucket contains 94% of records. "
                "Partition skew confirmed: df.groupBy('currency_code').count() showed SGD=1.8M, others<50K."
            ),
            "RESOLUTION": (
                "Added salting key to currency_code for the GroupBy (appended random suffix 0-9). "
                "Re-aggregated after join to remove salt. "
                "Alternatively used spark.sql.adaptive.skewJoin.enabled=true in Spark 3.x config. "
                "Partition sizes balanced: max 220K, min 95K after fix."
            ),
            "ROOT_CAUSE": "Skewed partition on currency_code — 94% of data in SGD bucket causing executor OOM",
            "RESOLUTION_CODE": "RC-SPARK-SKEW",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "oom",
            "RESOLVED_BY": "Carol Wong",
            "RESOLVED_DATE": "2024-10-20",
            "MTTD": 8, "MTTR": 60,
        },
        {
            "INCIDENT_ID": "INC-20240918-B003",
            "JOB_NAME": "DBS_SPARK_RISK_AGGREGATION",
            "SCRIPT_NAME": "DBS_SPARK_RISK_AGGREGATION.py",
            "COMMAND": "spark-submit --master yarn --deploy-mode cluster /jobs/DBS_SPARK_RISK_AGGREGATION.py --date 2024-09-18",
            "SUMMARY": "Spark job OOM — missing repartition before wide join causing shuffle spill",
            "INCIDENT_DETAILS": (
                "Stage 4 shuffle read failed. Executor lost: GC overhead limit exceeded. "
                "positions_df had 42 partitions (too few for 2.1GB dataset). "
                "Shuffle write 18GB to disk before executor crashed. "
                "spark.memory.fraction default 0.6 insufficient for this join size."
            ),
            "RESOLUTION": (
                "Added positions_df.repartition(400) before join. "
                "Set spark.memory.fraction=0.8 and spark.memory.storageFraction=0.3. "
                "Shuffle write reduced to 3.2GB. Job completed in 18 minutes."
            ),
            "ROOT_CAUSE": "Too few partitions before wide join causing large shuffle and executor OOM",
            "RESOLUTION_CODE": "RC-SPARK-MEM",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "oom",
            "RESOLVED_BY": "Frank Lim",
            "RESOLVED_DATE": "2024-09-18",
            "MTTD": 12, "MTTR": 50,
        },
        {
            "INCIDENT_ID": "INC-20240825-B004",
            "JOB_NAME": "DBS_SPARK_RISK_AGGREGATION",
            "SCRIPT_NAME": "DBS_SPARK_RISK_AGGREGATION.py",
            "COMMAND": "spark-submit --master yarn --deploy-mode cluster /jobs/DBS_SPARK_RISK_AGGREGATION.py --date 2024-08-25",
            "SUMMARY": "Spark driver OOM — df.collect() on 4.2GB result set",
            "INCIDENT_DETAILS": (
                "Driver JVM heap exhausted: java.lang.OutOfMemoryError: Java heap space at Driver. "
                "Script called result_df.collect() to iterate results in Python. "
                "Result set was 4.2GB — too large to fit in driver memory (spark.driver.memory=2g). "
                "SparkContext cancelled all running stages."
            ),
            "RESOLUTION": (
                "Replaced result_df.collect() with result_df.write.mode('overwrite').parquet(output_path). "
                "Removed Python-side iteration — output now consumed from Parquet by downstream job. "
                "Set spark.driver.memory=4g as precaution. Driver stable on next run."
            ),
            "ROOT_CAUSE": "df.collect() pulling 4.2GB result set into driver memory — driver OOM",
            "RESOLUTION_CODE": "RC-SPARK-DRIVER",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "oom",
            "RESOLVED_BY": "Grace Tan",
            "RESOLVED_DATE": "2024-08-25",
            "MTTD": 6, "MTTR": 30,
        },
        {
            "INCIDENT_ID": "INC-20240730-B005",
            "JOB_NAME": "DBS_SPARK_RISK_AGGREGATION",
            "SCRIPT_NAME": "DBS_SPARK_RISK_AGGREGATION.py",
            "COMMAND": "spark-submit --master yarn --deploy-mode cluster /jobs/DBS_SPARK_RISK_AGGREGATION.py --date 2024-07-30",
            "SUMMARY": "Broadcast join on 900MB table causing executor heap overflow",
            "INCIDENT_DETAILS": (
                "Script used spark.sql.functions.broadcast(risk_factors_df) to hint broadcast join. "
                "risk_factors_df grew to 900MB after new product types added in July release. "
                "spark.sql.autoBroadcastJoinThreshold default 10MB — hint overrode threshold. "
                "Broadcast serialisation failed: executor OOM attempting to hold 900MB in memory."
            ),
            "RESOLUTION": (
                "Removed broadcast() hint. Spark selected sort-merge join automatically. "
                "Added spark.sql.autoBroadcastJoinThreshold=-1 to disable auto-broadcast on this job. "
                "Join completed via shuffle in 22 minutes. No OOM."
            ),
            "ROOT_CAUSE": "Broadcast join hint on 900MB table — table grew beyond safe broadcast size",
            "RESOLUTION_CODE": "RC-SPARK-JOIN",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "oom",
            "RESOLVED_BY": "Daniel Lee",
            "RESOLVED_DATE": "2024-07-30",
            "MTTD": 9, "MTTR": 35,
        },
        {
            "INCIDENT_ID": "INC-20240611-B006",
            "JOB_NAME": "DBS_SPARK_RISK_AGGREGATION",
            "SCRIPT_NAME": "DBS_SPARK_RISK_AGGREGATION.py",
            "COMMAND": "spark-submit --master yarn --deploy-mode cluster /jobs/DBS_SPARK_RISK_AGGREGATION.py --date 2024-06-11",
            "SUMMARY": "GC overhead limit exceeded — Spark executor thrashing on repeated full GC",
            "INCIDENT_DETAILS": (
                "java.lang.OutOfMemoryError: GC overhead limit exceeded on executor 2 and 4. "
                "Heap dump showed large number of short-lived objects from Kryo serialisation. "
                "spark.serializer not configured — using Java serialisation (slower, more heap). "
                "Spark UI showed GC time > 98% of task time on failing executors."
            ),
            "RESOLUTION": (
                "Set spark.serializer=org.apache.spark.serializer.KryoSerializer. "
                "Registered custom classes: spark.kryo.registrationRequired=true. "
                "Reduced heap pressure — GC time dropped to 3%. Job completed in 16 minutes."
            ),
            "ROOT_CAUSE": "Java serialisation causing high GC pressure — KryoSerializer not configured",
            "RESOLUTION_CODE": "RC-SPARK-GC",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "oom",
            "RESOLVED_BY": "Jane Lim",
            "RESOLVED_DATE": "2024-06-11",
            "MTTD": 11, "MTTR": 40,
        },
    ]

    # ── Scenario C: Shell Script Permission Error ─────────────────────────────
    scenario_c = [
        {
            "INCIDENT_ID": "INC-20241101-C001",
            "JOB_NAME": "DBS_DAILY_ARCHIVE",
            "SCRIPT_NAME": "DBS_DAILY_ARCHIVE.sh",
            "COMMAND": "/bin/bash /jobs/DBS_DAILY_ARCHIVE.sh --date 2024-11-01",
            "SUMMARY": "Daily archive job ABEND RC=126 — permission denied on helper script",
            "INCIDENT_DETAILS": (
                "DBS_DAILY_ARCHIVE.sh called ./compress_and_move.sh at line 47 but exited immediately. "
                "TWS log: './compress_and_move.sh: Permission denied'. Exit code 126. "
                "script set -e so first non-zero exit terminates the job. "
                "Deployment pipeline copies scripts but does not call chmod +x."
            ),
            "RESOLUTION": (
                "SSH to edge node, ran: chmod +x /jobs/compress_and_move.sh. "
                "Updated Ansible deploy playbook to include: file: path=/jobs/*.sh mode=0755. "
                "Job re-ran and completed in 3 minutes."
            ),
            "ROOT_CAUSE": "chmod +x not applied to helper script after deploy",
            "RESOLUTION_CODE": "RC-PERM-CHMOD",
            "APPLICATION_CODE": "DBS-OPS",
            "FAILURE_TYPE": "permission_error",
            "RESOLVED_BY": "Alice Lim",
            "RESOLVED_DATE": "2024-11-01",
            "MTTD": 5, "MTTR": 15,
        },
        {
            "INCIDENT_ID": "INC-20240921-C002",
            "JOB_NAME": "DBS_DAILY_ARCHIVE",
            "SCRIPT_NAME": "DBS_DAILY_ARCHIVE.sh",
            "COMMAND": "/bin/bash /jobs/DBS_DAILY_ARCHIVE.sh --date 2024-09-21",
            "SUMMARY": "Archive job failed — CRLF line endings causing bash syntax error",
            "INCIDENT_DETAILS": (
                "Job failed with: /jobs/DBS_DAILY_ARCHIVE.sh: line 3: $'\\r': command not found. "
                "Script edited on Windows workstation — CRLF line endings embedded. "
                "Bash interpreter on Linux host rejects carriage returns as invalid tokens. "
                "Exit code 1. AWSBHV031E ABEND."
            ),
            "RESOLUTION": (
                "Ran: dos2unix /jobs/DBS_DAILY_ARCHIVE.sh. "
                "Updated Git pre-commit hook to enforce LF line endings for .sh files. "
                "Added .gitattributes: *.sh text eol=lf. Job re-ran successfully."
            ),
            "ROOT_CAUSE": "CRLF line endings from Windows editor — bash rejects carriage return tokens",
            "RESOLUTION_CODE": "RC-PERM-CRLF",
            "APPLICATION_CODE": "DBS-OPS",
            "FAILURE_TYPE": "permission_error",
            "RESOLVED_BY": "John Tan",
            "RESOLVED_DATE": "2024-09-21",
            "MTTD": 8, "MTTR": 20,
        },
        {
            "INCIDENT_ID": "INC-20240827-C003",
            "JOB_NAME": "DBS_DAILY_ARCHIVE",
            "SCRIPT_NAME": "DBS_DAILY_ARCHIVE.sh",
            "COMMAND": "/bin/bash /jobs/DBS_DAILY_ARCHIVE.sh --date 2024-08-27",
            "SUMMARY": "Archive ABEND — child script not executable after overnight deployment",
            "INCIDENT_DETAILS": (
                "compress_and_move.sh deployed by overnight batch deployment job. "
                "Deployment job uses rsync without --chmod=+x flag. "
                "File permissions reset to 0644 on destination host. "
                "DBS_DAILY_ARCHIVE.sh calls compress_and_move.sh directly (not via bash): Permission denied. "
                "Exit code 126."
            ),
            "RESOLUTION": (
                "Ran chmod +x /jobs/compress_and_move.sh. "
                "Fixed rsync command in deployment job: added --chmod=Du+x,go+rx,Fu+x. "
                "Added post-deploy health check that verifies script permissions."
            ),
            "ROOT_CAUSE": "rsync deployment without --chmod flag resets execute permission on scripts",
            "RESOLUTION_CODE": "RC-PERM-CHMOD",
            "APPLICATION_CODE": "DBS-OPS",
            "FAILURE_TYPE": "permission_error",
            "RESOLVED_BY": "David Lee",
            "RESOLVED_DATE": "2024-08-27",
            "MTTD": 6, "MTTR": 25,
        },
        {
            "INCIDENT_ID": "INC-20240712-C004",
            "JOB_NAME": "DBS_DAILY_ARCHIVE",
            "SCRIPT_NAME": "DBS_DAILY_ARCHIVE.sh",
            "COMMAND": "/bin/bash /jobs/DBS_DAILY_ARCHIVE.sh --date 2024-07-12",
            "SUMMARY": "Archive script deployed to wrong path — not found at expected location",
            "INCIDENT_DETAILS": (
                "DBS_DAILY_ARCHIVE.sh calls /opt/tws/utils/compress_and_move.sh. "
                "After infra migration, scripts moved to /jobs/utils/. "
                "TWS job definition still references old /opt/tws/utils/ path. "
                "Error: /opt/tws/utils/compress_and_move.sh: No such file or directory. Exit code 127."
            ),
            "RESOLUTION": (
                "Updated TWS job definition JOBCMD path to /jobs/utils/compress_and_move.sh. "
                "Created symlink: ln -s /jobs/utils /opt/tws/utils for backward compat. "
                "Updated deployment documentation with new path structure."
            ),
            "ROOT_CAUSE": "Script path not updated in TWS job definition after infrastructure migration",
            "RESOLUTION_CODE": "RC-PERM-PATH",
            "APPLICATION_CODE": "DBS-OPS",
            "FAILURE_TYPE": "permission_error",
            "RESOLVED_BY": "Sarah Wong",
            "RESOLVED_DATE": "2024-07-12",
            "MTTD": 10, "MTTR": 20,
        },
        {
            "INCIDENT_ID": "INC-20240605-C005",
            "JOB_NAME": "DBS_DAILY_ARCHIVE",
            "SCRIPT_NAME": "DBS_DAILY_ARCHIVE.sh",
            "COMMAND": "/bin/bash /jobs/DBS_DAILY_ARCHIVE.sh --date 2024-06-05",
            "SUMMARY": "Shell script syntax error — unterminated string in case statement",
            "INCIDENT_DETAILS": (
                "Script fails at line 89 with: syntax error near unexpected token 'fi'. "
                "Investigation showed missing closing quote in case) branch at line 82. "
                "Script edited via copy-paste from email — curly quote characters introduced. "
                "Bash treats curly quotes as literals, not string delimiters."
            ),
            "RESOLUTION": (
                "Fixed syntax: replaced curly quotes with straight ASCII quotes in script. "
                "Ran shellcheck /jobs/DBS_DAILY_ARCHIVE.sh — no more warnings. "
                "Added shellcheck to pre-commit hook for all .sh files."
            ),
            "ROOT_CAUSE": "Curly/smart quotes introduced from email copy-paste break bash string parsing",
            "RESOLUTION_CODE": "RC-PERM-SYNTAX",
            "APPLICATION_CODE": "DBS-OPS",
            "FAILURE_TYPE": "permission_error",
            "RESOLVED_BY": "Mike Chen",
            "RESOLVED_DATE": "2024-06-05",
            "MTTD": 7, "MTTR": 15,
        },
    ]

    # ── Scenario D: Python Version Mismatch ──────────────────────────────────
    scenario_d = [
        {
            "INCIDENT_ID": "INC-20241030-D001",
            "JOB_NAME": "DBS_CREDIT_SCORE_CALC",
            "SCRIPT_NAME": "DBS_CREDIT_SCORE_CALC.py",
            "COMMAND": "/usr/bin/python /jobs/DBS_CREDIT_SCORE_CALC.py --date 2024-10-30",
            "SUMMARY": "Credit score job ABEND — walrus operator SyntaxError under Python 2.7",
            "INCIDENT_DETAILS": (
                "Job failed immediately with: SyntaxError: invalid syntax at line 34. "
                "Line 34: if (result := fetch_score(cust_id)) is not None: "
                "Walrus operator := requires Python 3.8+. "
                "TWS JOBCMD set to /usr/bin/python which resolves to Python 2.7.18 on this host. "
                "Script shebang is #!/usr/bin/env python3 but TWS overrides with JOBCMD."
            ),
            "RESOLUTION": (
                "Updated TWS job definition JOBCMD from '/usr/bin/python' to '/usr/bin/python3'. "
                "Verified python3 --version: Python 3.9.18 on execution host. "
                "Job re-ran successfully. Python 2.7 removed from host as part of security hardening."
            ),
            "ROOT_CAUSE": "TWS JOBCMD pointing to /usr/bin/python (Python 2.7) — walrus operator syntax requires Python 3.8+",
            "RESOLUTION_CODE": "RC-PY-VERSION",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "python_version",
            "RESOLVED_BY": "Emma Chen",
            "RESOLVED_DATE": "2024-10-30",
            "MTTD": 3, "MTTR": 10,
        },
        {
            "INCIDENT_ID": "INC-20240919-D002",
            "JOB_NAME": "DBS_CREDIT_SCORE_CALC",
            "SCRIPT_NAME": "DBS_CREDIT_SCORE_CALC.py",
            "COMMAND": "/usr/bin/python3 /jobs/DBS_CREDIT_SCORE_CALC.py --date 2024-09-19",
            "SUMMARY": "Python 3.6 interpreter — walrus operator not supported in this version",
            "INCIDENT_DETAILS": (
                "SyntaxError: invalid syntax at line 34 despite JOBCMD using python3. "
                "python3 --version on host returned: Python 3.6.9. "
                "Walrus operator := introduced in Python 3.8 (PEP 572). "
                "Execution host running Ubuntu 18.04 with default Python 3.6 package."
            ),
            "RESOLUTION": (
                "Installed Python 3.9 via deadsnakes PPA: apt install python3.9. "
                "Updated TWS JOBCMD to /usr/bin/python3.9. "
                "Alternatively: rewrote line 34 to avoid walrus operator for Python 3.6 compat. "
                "Infra team scheduled upgrade of all batch hosts to Ubuntu 22.04 (Python 3.10)."
            ),
            "ROOT_CAUSE": "Execution host running Python 3.6 — walrus operator requires 3.8+",
            "RESOLUTION_CODE": "RC-PY-VERSION",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "python_version",
            "RESOLVED_BY": "Frank Lim",
            "RESOLVED_DATE": "2024-09-19",
            "MTTD": 5, "MTTR": 25,
        },
        {
            "INCIDENT_ID": "INC-20240820-D003",
            "JOB_NAME": "DBS_CREDIT_SCORE_CALC",
            "SCRIPT_NAME": "DBS_CREDIT_SCORE_CALC.py",
            "COMMAND": "python3 /jobs/DBS_CREDIT_SCORE_CALC.py --date 2024-08-20",
            "SUMMARY": "ModuleNotFoundError: scikit-learn not installed on execution host",
            "INCIDENT_DETAILS": (
                "Job failed with: ModuleNotFoundError: No module named 'sklearn'. "
                "scikit-learn installed in dev venv but not in system Python3 on batch host. "
                "TWS job does not activate virtualenv before invoking script. "
                "Script imports: from sklearn.preprocessing import StandardScaler at line 8."
            ),
            "RESOLUTION": (
                "Two options applied: (1) pip3 install scikit-learn on batch host system Python. "
                "(2) Updated JOBCMD to activate venv first: source /opt/venvs/credit/bin/activate && python3 /jobs/DBS_CREDIT_SCORE_CALC.py. "
                "Option 2 preferred — keeps dependencies isolated. Job re-ran successfully."
            ),
            "ROOT_CAUSE": "scikit-learn installed in venv but JOBCMD not activating venv",
            "RESOLUTION_CODE": "RC-PY-MODULE",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "python_version",
            "RESOLVED_BY": "Grace Tan",
            "RESOLVED_DATE": "2024-08-20",
            "MTTD": 4, "MTTR": 15,
        },
        {
            "INCIDENT_ID": "INC-20240708-D004",
            "JOB_NAME": "DBS_CREDIT_SCORE_CALC",
            "SCRIPT_NAME": "DBS_CREDIT_SCORE_CALC.py",
            "COMMAND": "/usr/bin/python /jobs/DBS_CREDIT_SCORE_CALC.py --date 2024-07-08",
            "SUMMARY": "f-string SyntaxError — TWS JOBCMD using Python 2.7 (/usr/bin/python)",
            "INCIDENT_DETAILS": (
                "SyntaxError: invalid syntax at line 12. "
                "Line 12: logger.info(f'Processing customer {cust_id} score'). "
                "f-strings require Python 3.6+. /usr/bin/python = Python 2.7. "
                "Script introduced f-strings in last release. Prior version used % formatting."
            ),
            "RESOLUTION": (
                "Updated JOBCMD to /usr/bin/python3. Verified Python 3.9 available. "
                "Created checklist for dev team: before release, verify JOBCMD Python version on all hosts. "
                "Added CI pipeline step: python3 -m py_compile DBS_CREDIT_SCORE_CALC.py."
            ),
            "ROOT_CAUSE": "f-string syntax requires Python 3.6+ but JOBCMD using /usr/bin/python (2.7)",
            "RESOLUTION_CODE": "RC-PY-VERSION",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "python_version",
            "RESOLVED_BY": "Bob Tan",
            "RESOLVED_DATE": "2024-07-08",
            "MTTD": 3, "MTTR": 10,
        },
        {
            "INCIDENT_ID": "INC-20240602-D005",
            "JOB_NAME": "DBS_CREDIT_SCORE_CALC",
            "SCRIPT_NAME": "DBS_CREDIT_SCORE_CALC.py",
            "COMMAND": "python3 /jobs/DBS_CREDIT_SCORE_CALC.py --date 2024-06-02",
            "SUMMARY": "venv not activated — pandas version mismatch causes AttributeError",
            "INCIDENT_DETAILS": (
                "AttributeError: 'DataFrame' object has no attribute 'swapaxes'. "
                "pandas removed swapaxes in 2.0. System pandas is 1.5.3; venv has 2.1.0. "
                "Script was written for pandas 2.x API. JOBCMD not activating venv. "
                "System Python3 uses old pandas without the required DataFrame API."
            ),
            "RESOLUTION": (
                "Updated JOBCMD: source /opt/venvs/credit/bin/activate && python3 /jobs/DBS_CREDIT_SCORE_CALC.py. "
                "Verified venv pandas version: 2.1.0. "
                "Added venv activation check at top of script: assert pd.__version__ >= '2.0'."
            ),
            "ROOT_CAUSE": "venv not activated — system pandas 1.5.3 does not support pandas 2.x API",
            "RESOLUTION_CODE": "RC-PY-MODULE",
            "APPLICATION_CODE": "DBS-RISK",
            "FAILURE_TYPE": "python_version",
            "RESOLVED_BY": "Carol Wong",
            "RESOLVED_DATE": "2024-06-02",
            "MTTD": 6, "MTTR": 20,
        },
    ]

    # ── Scenario E: Upstream Dependency / HOLD ───────────────────────────────
    scenario_e = [
        {
            "INCIDENT_ID": "INC-20241102-E001",
            "JOB_NAME": "DBS_FX_SETTLEMENT_FLOW",
            "SCRIPT_NAME": "DBS_FX_SETTLEMENT_FLOW.py",
            "COMMAND": "python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date 2024-11-02 --currency SGD",
            "SUMMARY": "FX settlement job not started — predecessor DBS_FX_NETTING_CALC in HOLD",
            "INCIDENT_DETAILS": (
                "AWSBHV026E: Job stream FX_SETTLEMENT not submitted. "
                "Predecessor DBS_FX_NETTING_CALC in HOLD state — manual release not performed. "
                "DBS_FX_SETTLEMENT_FLOW has dependency on DBS_FX_NETTING_CALC completing with RC=0. "
                "HOLD was placed by on-call engineer during previous night's incident — not released after resolution."
            ),
            "RESOLUTION": (
                "Released HOLD on DBS_FX_NETTING_CALC via TWS console (conman command: release job). "
                "DBS_FX_NETTING_CALC completed in 12 minutes. "
                "DBS_FX_SETTLEMENT_FLOW auto-triggered and completed within SLA. "
                "Updated runbook: HOLD release checklist to be verified at end of every incident."
            ),
            "ROOT_CAUSE": "Predecessor job in HOLD state from prior incident — not released before settlement window",
            "RESOLUTION_CODE": "RC-TWS-HOLD",
            "APPLICATION_CODE": "DBS-FX",
            "FAILURE_TYPE": "upstream_dependency",
            "RESOLVED_BY": "Daniel Lee",
            "RESOLVED_DATE": "2024-11-02",
            "MTTD": 8, "MTTR": 25,
        },
        {
            "INCIDENT_ID": "INC-20241015-E002",
            "JOB_NAME": "DBS_FX_SETTLEMENT_FLOW",
            "SCRIPT_NAME": "DBS_FX_SETTLEMENT_FLOW.py",
            "COMMAND": "python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date 2024-10-15 --currency SGD",
            "SUMMARY": "Settlement job AWSBHV026E — predecessor FX netting job did not complete",
            "INCIDENT_DETAILS": (
                "AWSBHV026E: DBS_FX_NETTING_CALC did not complete successfully. "
                "Netting job was in RUNNING state beyond its expected 30-minute window. "
                "Netting job stalled waiting for FX rate source API response (timeout 300s exceeded). "
                "Settlement job missed its 17:30 SGT trigger window."
            ),
            "RESOLUTION": (
                "Restarted FX rate source connectivity from netting job host. "
                "Netting job completed after 6 minutes. "
                "Resubmitted DBS_FX_SETTLEMENT_FLOW manually via TWS console. "
                "Completed within extended SLA window."
            ),
            "ROOT_CAUSE": "Predecessor job stalled on FX rate source API timeout — settlement auto-trigger missed",
            "RESOLUTION_CODE": "RC-TWS-UPSTREAM",
            "APPLICATION_CODE": "DBS-FX",
            "FAILURE_TYPE": "upstream_dependency",
            "RESOLVED_BY": "Emma Chen",
            "RESOLVED_DATE": "2024-10-15",
            "MTTD": 12, "MTTR": 35,
        },
        {
            "INCIDENT_ID": "INC-20240917-E003",
            "JOB_NAME": "DBS_FX_SETTLEMENT_FLOW",
            "SCRIPT_NAME": "DBS_FX_SETTLEMENT_FLOW.py",
            "COMMAND": "python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date 2024-09-17 --currency SGD",
            "SUMMARY": "FX settlement not triggered — upstream FX feed job timed out",
            "INCIDENT_DETAILS": (
                "DBS_FX_FEED_SG abended at 16:45 — Reuters rate feed timeout after 300s. "
                "DBS_FX_NETTING_CALC depends on DBS_FX_FEED_SG completing. "
                "Netting job not submitted — cascade trigger failed. "
                "Settlement missed cut-off. AWSBHV026E in TWS event log."
            ),
            "RESOLUTION": (
                "Reuters feed connectivity issue resolved by network team. "
                "Manually resubmitted DBS_FX_FEED_SG — completed in 4 minutes. "
                "Netting job auto-triggered and completed. Settlement resubmitted and completed."
            ),
            "ROOT_CAUSE": "External FX feed timeout caused cascade failure in TWS job dependency chain",
            "RESOLUTION_CODE": "RC-TWS-UPSTREAM",
            "APPLICATION_CODE": "DBS-FX",
            "FAILURE_TYPE": "upstream_dependency",
            "RESOLVED_BY": "Sarah Wong",
            "RESOLVED_DATE": "2024-09-17",
            "MTTD": 15, "MTTR": 45,
        },
        {
            "INCIDENT_ID": "INC-20240818-E004",
            "JOB_NAME": "DBS_FX_SETTLEMENT_FLOW",
            "SCRIPT_NAME": "DBS_FX_SETTLEMENT_FLOW.py",
            "COMMAND": "python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date 2024-08-18 --currency SGD",
            "SUMMARY": "Settlement not triggered — predecessor ABEND caused cascade HOLD",
            "INCIDENT_DETAILS": (
                "DBS_FX_NETTING_CALC ABEND with RC=2 (database connection refused). "
                "TWS dependency: on ABEND, downstream jobs placed in cascade HOLD. "
                "DBS_FX_SETTLEMENT_FLOW auto-placed in HOLD by TWS dependency manager. "
                "No alert configured for cascade HOLD — detected 40 minutes later."
            ),
            "RESOLUTION": (
                "Fixed DB connection issue on netting job host (firewall rule had expired). "
                "Released cascade HOLD on settlement job. Both jobs resubmitted and completed. "
                "Added SNMP alert for cascade HOLD events in TWS."
            ),
            "ROOT_CAUSE": "Predecessor ABEND caused TWS cascade HOLD on downstream settlement job",
            "RESOLUTION_CODE": "RC-TWS-HOLD",
            "APPLICATION_CODE": "DBS-FX",
            "FAILURE_TYPE": "upstream_dependency",
            "RESOLVED_BY": "Mike Chen",
            "RESOLVED_DATE": "2024-08-18",
            "MTTD": 40, "MTTR": 65,
        },
        {
            "INCIDENT_ID": "INC-20240714-E005",
            "JOB_NAME": "DBS_FX_SETTLEMENT_FLOW",
            "SCRIPT_NAME": "DBS_FX_SETTLEMENT_FLOW.py",
            "COMMAND": "python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date 2024-07-14 --currency SGD",
            "SUMMARY": "TWS job stream not submitted — plan not updated after dependency change",
            "INCIDENT_DETAILS": (
                "New job DBS_FX_RISK_CHECK added to FX pipeline between netting and settlement. "
                "TWS plan not updated to reflect new dependency. "
                "DBS_FX_SETTLEMENT_FLOW still configured to depend on DBS_FX_NETTING_CALC directly. "
                "DBS_FX_RISK_CHECK inserted but settlement trigger logic not updated — job stream not submitted."
            ),
            "RESOLUTION": (
                "Updated TWS job stream definition: added DBS_FX_RISK_CHECK as prerequisite for settlement. "
                "Tested in UAT TWS environment. Deployed to prod. Job stream submitted correctly."
            ),
            "ROOT_CAUSE": "TWS plan not updated after new job inserted into FX pipeline dependency chain",
            "RESOLUTION_CODE": "RC-TWS-CONFIG",
            "APPLICATION_CODE": "DBS-FX",
            "FAILURE_TYPE": "upstream_dependency",
            "RESOLVED_BY": "Alice Lim",
            "RESOLVED_DATE": "2024-07-14",
            "MTTD": 20, "MTTR": 90,
        },
        {
            "INCIDENT_ID": "INC-20240603-E006",
            "JOB_NAME": "DBS_FX_SETTLEMENT_FLOW",
            "SCRIPT_NAME": "DBS_FX_SETTLEMENT_FLOW.py",
            "COMMAND": "python3 /jobs/DBS_FX_SETTLEMENT_FLOW.py --date 2024-06-03 --currency SGD",
            "SUMMARY": "Settlement missed cut-off — netting job in HOLD from weekend maintenance",
            "INCIDENT_DETAILS": (
                "Weekend maintenance placed DBS_FX_NETTING_CALC in HOLD for patching. "
                "Patch completed Friday night. HOLD not released — maintenance team assumed it would auto-release. "
                "Monday morning settlement job attempted trigger but predecessor still in HOLD. "
                "AWSBHV026E: job stream FX_SETTLEMENT not submitted."
            ),
            "RESOLUTION": (
                "Released HOLD on DBS_FX_NETTING_CALC. Netting and settlement completed within 30 minutes. "
                "Added to maintenance runbook: HOLD release verification step before sign-off. "
                "Scheduled post-maintenance automated check script."
            ),
            "ROOT_CAUSE": "Weekend maintenance HOLD not released — predecessor still in HOLD on Monday",
            "RESOLUTION_CODE": "RC-TWS-HOLD",
            "APPLICATION_CODE": "DBS-FX",
            "FAILURE_TYPE": "upstream_dependency",
            "RESOLVED_BY": "John Tan",
            "RESOLVED_DATE": "2024-06-03",
            "MTTD": 25, "MTTR": 40,
        },
    ]

    # ── Scenario F: Unknown / Insufficient Data ───────────────────────────────
    scenario_f = [
        {
            "INCIDENT_ID": "INC-20241105-F001",
            "JOB_NAME": "DBS_CBDC_LEDGER_SYNC",
            "SCRIPT_NAME": "DBS_CBDC_LEDGER_SYNC.py",
            "COMMAND": "python3 /jobs/DBS_CBDC_LEDGER_SYNC.py --network mainnet",
            "SUMMARY": "CBDC ledger sync ABEND RC=255 — unhandled exception, no useful log output",
            "INCIDENT_DETAILS": (
                "New CBDC job first production run. ABEND RC=255 — unhandled exception in job process. "
                "No stack trace in TWS log. Script may be suppressing exceptions. "
                "No prior incident history for this job. Dev team still onboarding."
            ),
            "RESOLUTION": (
                "Escalated to L2. Dev team added exception logging. Root cause TBD pending investigation."
            ),
            "ROOT_CAUSE": "Unknown — insufficient log output from first production run",
            "RESOLUTION_CODE": "RC-UNKNOWN",
            "APPLICATION_CODE": "DBS-CBDC",
            "FAILURE_TYPE": "unknown",
            "RESOLVED_BY": "L2 Team",
            "RESOLVED_DATE": "2024-11-05",
            "MTTD": 5, "MTTR": 120,
        },
        {
            "INCIDENT_ID": "INC-20241020-F002",
            "JOB_NAME": "DBS_CBDC_LEDGER_SYNC",
            "SCRIPT_NAME": "DBS_CBDC_LEDGER_SYNC.py",
            "COMMAND": "python3 /jobs/DBS_CBDC_LEDGER_SYNC.py --network mainnet",
            "SUMMARY": "CBDC job intermittent failure — no consistent pattern identified",
            "INCIDENT_DETAILS": (
                "Job ABEND RC=1 on second run. Partial log available: 'Connection reset by peer'. "
                "Network team found no issues at time of failure. "
                "Intermittent — re-ran 30 minutes later and succeeded. No root cause determined."
            ),
            "RESOLUTION": (
                "Added retry logic in script (3 attempts with 30s backoff). "
                "Root cause not fully determined — suspected transient network issue."
            ),
            "ROOT_CAUSE": "Suspected transient network — unconfirmed, escalated",
            "RESOLUTION_CODE": "RC-UNKNOWN",
            "APPLICATION_CODE": "DBS-CBDC",
            "FAILURE_TYPE": "unknown",
            "RESOLVED_BY": "L2 Team",
            "RESOLVED_DATE": "2024-10-20",
            "MTTD": 10, "MTTR": 90,
        },
        {
            "INCIDENT_ID": "INC-20240912-F003",
            "JOB_NAME": "DBS_CBDC_LEDGER_SYNC",
            "SCRIPT_NAME": "DBS_CBDC_LEDGER_SYNC.py",
            "COMMAND": "python3 /jobs/DBS_CBDC_LEDGER_SYNC.py --network mainnet",
            "SUMMARY": "CBDC sync ABEND — log file missing, cannot determine failure reason",
            "INCIDENT_DETAILS": (
                "Job ABEND RC=255 but log file was not created. "
                "Possible disk space issue on log host — /var/log 98% full at time of failure. "
                "No stack trace available. TWS only shows exit code."
            ),
            "RESOLUTION": (
                "Cleared /var/log space (removed logs older than 30 days). "
                "Job re-ran and completed. Root cause of original failure not confirmed."
            ),
            "ROOT_CAUSE": "Possible disk full on log host — root cause unconfirmed",
            "RESOLUTION_CODE": "RC-UNKNOWN",
            "APPLICATION_CODE": "DBS-CBDC",
            "FAILURE_TYPE": "unknown",
            "RESOLVED_BY": "L2 Team",
            "RESOLVED_DATE": "2024-09-12",
            "MTTD": 15, "MTTR": 60,
        },
        {
            "INCIDENT_ID": "INC-20240820-F004",
            "JOB_NAME": "DBS_CBDC_LEDGER_SYNC",
            "SCRIPT_NAME": "DBS_CBDC_LEDGER_SYNC.py",
            "COMMAND": "python3 /jobs/DBS_CBDC_LEDGER_SYNC.py --network mainnet --debug",
            "SUMMARY": "CBDC sync failure after config change — unclear which config broke it",
            "INCIDENT_DETAILS": (
                "Job ABEND RC=1 after deployment of new config. "
                "Three config files updated in same deployment — unclear which caused failure. "
                "Partial log: 'Configuration validation failed'. No specific field mentioned in log."
            ),
            "RESOLUTION": (
                "Rolled back all three config files to previous versions. Job ran successfully. "
                "Change isolation in progress — will re-apply configs one at a time to identify culprit."
            ),
            "ROOT_CAUSE": "Config validation failure — specific field unknown pending change isolation",
            "RESOLUTION_CODE": "RC-UNKNOWN",
            "APPLICATION_CODE": "DBS-CBDC",
            "FAILURE_TYPE": "unknown",
            "RESOLVED_BY": "L2 Team",
            "RESOLVED_DATE": "2024-08-20",
            "MTTD": 20, "MTTR": 45,
        },
    ]

    all_tickets = scenario_a + scenario_b + scenario_c + scenario_d + scenario_e + scenario_f
    df = pd.DataFrame(all_tickets)
    df.to_excel("ichamp_tickets_dummy.xlsx", index=False)
    logger.info(f"Created ichamp_tickets_dummy.xlsx with {len(all_tickets)} tickets across 6 scenarios")
    return df


def vectorize_excel(recreate: bool = False):
    """Read Excel and vectorize into ChromaDB using provider from config."""
    config = load_config()

    embedding_provider = config.get("embedding", {}).get("provider", "vertexai")
    if embedding_provider == "local":
        from app.agent.tools import LocalEmbeddingClient
        embedding_client = LocalEmbeddingClient(config)
    else:
        from app.agent.tools import VertexAIEmbeddingClient
        embedding_client = VertexAIEmbeddingClient(config)

    from app.agent.tools import ChromaDBVectorStore
    vector_db = ChromaDBVectorStore(config.get("vector_db", {}), embedding_client)

    if recreate:
        logger.info("--recreate flag set: clearing existing ChromaDB collection")
        vector_db.clear()

    df = pd.read_excel("ichamp_tickets_dummy.xlsx")

    tickets = []
    for _, row in df.iterrows():
        ticket = {
            "ticket_id":        str(row["INCIDENT_ID"]),
            "job_name":         str(row["JOB_NAME"]),
            "script_name":      str(row.get("SCRIPT_NAME", "")),
            "command":          str(row.get("COMMAND", "")),
            "summary":          str(row.get("SUMMARY", "")),
            "incident_details": str(row.get("INCIDENT_DETAILS", "")),
            "resolution":       str(row.get("RESOLUTION", "")),
            "failure_type":     str(row.get("FAILURE_TYPE", "unknown")),
            "resolved_by":      str(row.get("RESOLVED_BY", "")),
            "resolved_at":      str(row.get("RESOLVED_DATE", "")),
        }
        tickets.append(ticket)

    vector_db.add_documents(tickets)
    logger.info(f"Vectorized {len(tickets)} tickets into ChromaDB (provider: {embedding_provider})")
    logger.info(f"Total documents in DB: {vector_db.get_count()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build OpsPilot vector database from iChamp dummy data")
    parser.add_argument(
        "--recreate", action="store_true",
        help="Clear the existing ChromaDB collection before inserting. Required when switching embedding providers (different vector dimensions)."
    )
    args = parser.parse_args()

    create_dummy_excel()
    vectorize_excel(recreate=args.recreate)
    print("\nDone! Vector DB created at ./chroma_data/")
    print("Verify: python -m app.main then GET http://localhost:8000/vector-db/count")
    print("Expected count: 32")
