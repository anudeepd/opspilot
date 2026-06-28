#!/usr/bin/env python3
"""
DBS_SPARK_RISK_AGGREGATION.py — Daily risk aggregation job (PySpark on YARN).

TWS JOBCMD:
  spark-submit --master yarn --deploy-mode cluster \
    /jobs/DBS_SPARK_RISK_AGGREGATION.py --date YYYY-MM-DD

Known issues (pre-fix):
  - spark.executor.memory not set → defaults to 1g (too low for 2.1GB + 800MB join)
  - No repartition() before large join → 18GB shuffle write, executor OOM
  - df.collect() on 4.2GB result → driver OOM
  - broadcast() hint on 900MB table → exceeds safe broadcast size

Fix applied (INC-20241103-B001):
  - spark.executor.memory=6g, spark.executor.cores=4 in spark-submit
  - positions_df.repartition(200) added before join
  - df.collect() replaced with df.write.parquet(output_path)
"""

import argparse
import logging
import sys
import os

logger = logging.getLogger("DBS_SPARK_RISK_AGGREGATION")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

POSITIONS_PATH = "hdfs://dbs-hdfs/data/positions"
RISK_FACTORS_PATH = "hdfs://dbs-hdfs/data/risk_factors"
OUTPUT_PATH = "hdfs://dbs-hdfs/output/risk_aggregation"


def create_spark_session():
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        logger.error("PySpark not available. This script must be run via spark-submit.")
        sys.exit(1)

    return (
        SparkSession.builder
        .appName("DBS_SPARK_RISK_AGGREGATION")
        # spark.executor.memory and spark.executor.cores should be set in spark-submit args
        # Recommended: --conf spark.executor.memory=6g --conf spark.executor.cores=4
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.skewJoin.enabled", "true")
        .getOrCreate()
    )


def run_risk_aggregation(spark, run_date: str):
    from pyspark.sql import functions as F

    logger.info(f"Loading positions data for date {run_date}")
    positions_df = (
        spark.read.parquet(f"{POSITIONS_PATH}/date={run_date}")
        # Fix: repartition before join to avoid large shuffle
        .repartition(200, "position_id")
    )

    logger.info("Loading risk factors")
    risk_factors_df = spark.read.parquet(RISK_FACTORS_PATH)
    # KNOWN ISSUE (pre-fix): broadcast hint on 900MB table causes executor OOM
    # risk_factors_df = F.broadcast(risk_factors_df)  # DO NOT USE when table > 200MB

    logger.info(f"Positions count: {positions_df.count()}, Risk factors count: {risk_factors_df.count()}")

    logger.info("Joining positions with risk factors")
    joined_df = positions_df.join(risk_factors_df, on="instrument_id", how="left")

    logger.info("Aggregating risk by portfolio and currency")
    result_df = (
        joined_df
        .groupBy("portfolio_id", "currency_code")
        .agg(
            F.sum("notional_value").alias("total_notional"),
            F.sum("risk_weight").alias("total_risk"),
            F.count("position_id").alias("position_count"),
        )
    )

    output_path = f"{OUTPUT_PATH}/date={run_date}"
    logger.info(f"Writing results to {output_path}")

    # Fix: write to parquet instead of collect() which causes driver OOM
    # KNOWN ISSUE (pre-fix): result_df.collect() — pulls 4.2GB to driver memory
    result_df.write.mode("overwrite").parquet(output_path)

    logger.info(f"Risk aggregation complete. Output: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    args = parser.parse_args()

    spark = create_spark_session()
    try:
        run_risk_aggregation(spark, args.date)
    finally:
        spark.stop()
