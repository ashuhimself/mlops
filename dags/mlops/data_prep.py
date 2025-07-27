from __future__ import annotations
from datetime import datetime, timedelta
import io
import json
import pickle
import numpy as np
import pandas as pd
from airflow import DAG
from airflow.decorators import task
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

DEFAULT_ARGS = dict(
    owner="ml-team",
    depends_on_past=False,
    start_date=datetime(2024, 1, 1),
    email_on_failure=False,
    email_on_retry=False,
    retries=2,
    retry_delay=timedelta(minutes=5),
)

BUCKET = "features"
AWS_CONN_ID = "minio_s3"

with DAG(
    dag_id="data_gen_and_prep_pipeline",
    default_args=DEFAULT_ARGS,
    schedule="@daily",
    catchup=False,
    tags=["data-generation", "data-preparation", "ml-pipeline"],
    doc_md=__doc__,
) as dag:

    @task
    def generate_and_upload(ds: str) -> dict:
        date_seed = int(ds.replace("-", ""))
        np.random.seed(date_seed)

        base_records = 1000
        daily_variation = np.random.randint(-200, 300)
        n_records = base_records + daily_variation

        data = pd.DataFrame({
            "customer_id": [f"CUST_{i:06d}" for i in range(n_records)],
            "age": np.random.normal(45, 15, n_records).clip(18, 80).astype(int),
            "income": np.random.lognormal(10.5, 0.6, n_records),
            "credit_score": np.random.normal(700, 100, n_records).clip(300, 850).astype(int),
            "account_length_days": np.random.exponential(365, n_records).astype(int),
            "num_products": np.random.poisson(2, n_records).clip(1, 10),
            "total_spend_last_30d": np.random.exponential(500, n_records),
            "num_transactions_last_30d": np.random.poisson(15, n_records),
            "region": np.random.choice(["North", "South", "East", "West"], n_records),
            "customer_segment": np.random.choice(["Premium", "Standard", "Basic"], n_records, p=[0.2, 0.5, 0.3]),
            "has_mobile_app": np.random.choice([True, False], n_records, p=[0.7, 0.3]),
            "email_opens_last_30d": np.random.poisson(5, n_records),
            "support_tickets_last_90d": np.random.poisson(0.5, n_records),
            "timestamp": pd.to_datetime(ds) + pd.to_timedelta(np.random.randint(0, 86400, n_records), unit="s"),
        })

        churn_score = (
            -0.002 * data["account_length_days"]
            -0.001 * data["credit_score"]
            +0.02  * data["support_tickets_last_90d"]
            -0.5   * data["has_mobile_app"]
            -0.01  * data["email_opens_last_30d"]
            +0.001 * data["age"]
            -0.3   * data["num_products"]
            +np.random.normal(0, 0.1, n_records)
        )
        data["churn_probability"] = 1 / (1 + np.exp(-churn_score))

        missing_idx = np.random.choice(n_records, size=int(0.05 * n_records), replace=False)
        data.loc[missing_idx, "email_opens_last_30d"] = np.nan

        outlier_idx = np.random.choice(n_records, size=int(0.02 * n_records), replace=False)
        data.loc[outlier_idx, "total_spend_last_30d"] *= 10

        year, month, day = ds.split("-")
        raw_key = f"raw_data/year={year}/month={month}/day={day}/customer_data_{ds}.parquet"

        buf = io.BytesIO()
        data.to_parquet(buf, index=False, compression="snappy")
        hook = S3Hook(aws_conn_id=AWS_CONN_ID)
        hook.load_bytes(buf.getvalue(), key=raw_key, bucket_name=BUCKET, replace=True)

        return {"raw_key": raw_key, "ds": ds}

    @task
    def engineer_features(meta: dict) -> dict:
        hook = S3Hook(aws_conn_id=AWS_CONN_ID)
        obj = hook.get_key(key=meta["raw_key"], bucket_name=BUCKET)
        buf = io.BytesIO(obj.get()["Body"].read())
        df = pd.read_parquet(buf)

        df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
        df["spend_per_transaction"] = df["total_spend_last_30d"] / (df["num_transactions_last_30d"] + 1)

        processed_key = meta["raw_key"].replace("raw_data", "prepared_data").replace("customer_data", "processed_data")
        pbuf = io.BytesIO()
        df.to_parquet(pbuf, index=False, compression="snappy")
        hook.load_bytes(pbuf.getvalue(), key=processed_key, bucket_name=BUCKET, replace=True)

        meta["processed_key"] = processed_key
        return meta

    @task
    def prepare_ml_datasets(meta: dict) -> dict:
        hook = S3Hook(aws_conn_id=AWS_CONN_ID)
        obj = hook.get_key(key=meta["processed_key"], bucket_name=BUCKET)
        buf = io.BytesIO(obj.get()["Body"].read())
        df = pd.read_parquet(buf)

        label_col = "churn_probability"
        base_df = df.drop(columns=["customer_id", "timestamp"], errors="ignore")

        obj_cols = base_df.select_dtypes(include=["object"]).columns.tolist()
        base_df = pd.get_dummies(base_df, columns=obj_cols, drop_first=True)

        feature_cols = [c for c in base_df.columns if c != label_col]

        base_df.replace([np.inf, -np.inf], np.nan, inplace=True)
        base_df[feature_cols] = base_df[feature_cols].fillna(0.0)
        base_df[feature_cols] = base_df[feature_cols].astype(np.float32)

        numeric_cols = base_df[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
        scaler = StandardScaler()
        base_df[numeric_cols] = scaler.fit_transform(base_df[numeric_cols])

        X = base_df[feature_cols]
        y = df[label_col]
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        year, month, day = meta["ds"].split("-")
        saved_paths = {}
        for name, dataset in {"X_train": X_train, "X_test": X_test, "y_train": y_train, "y_test": y_test}.items():
            pbuf = io.BytesIO()
            (dataset.to_frame(name) if isinstance(dataset, pd.Series) else dataset).to_parquet(pbuf, index=False)
            key = f"prepared_data/year={year}/month={month}/day={day}/{name}.parquet"
            hook.load_bytes(pbuf.getvalue(), key=key, bucket_name=BUCKET, replace=True)
            saved_paths[name] = f"s3://{BUCKET}/{key}"

        scaler_buf = io.BytesIO()
        pickle.dump(scaler, scaler_buf)
        scaler_key = f"prepared_data/year={year}/month={month}/day={day}/scaler.pkl"
        hook.load_bytes(scaler_buf.getvalue(), key=scaler_key, bucket_name=BUCKET, replace=True)

        schema = {
            "feature_columns": feature_cols,
            "numeric_columns": numeric_cols,
            "label_col": label_col,
            "prepared_partition": f"year={year}/month={month}/day={day}"
        }
        schema_key = f"prepared_data/year={year}/month={month}/day={day}/feature_schema.json"
        hook.load_string(json.dumps(schema, indent=2), key=schema_key, bucket_name=BUCKET, replace=True)

        meta["ml_paths"] = saved_paths
        meta["scaler_key"] = f"s3://{BUCKET}/{scaler_key}"
        meta["schema_key"] = f"s3://{BUCKET}/{schema_key}"
        return meta

    prepare_ml_datasets(engineer_features(generate_and_upload()))
