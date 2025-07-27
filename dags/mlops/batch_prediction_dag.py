"""
Batch Prediction Pipeline
Loads latest staged model, aligns to its signature, applies the exact scaler, scores, writes results
Also runs a synthetic sanity check batch and saves both raw and predicted outputs
"""

from datetime import datetime, timedelta
import io
import json
import pickle
import numpy as np
import pandas as pd
import mlflow
import mlflow.pyfunc
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook

try:
    from airflow.sdk import Variable
except ImportError:
    from airflow.models import Variable

default_args = dict(
    owner="ml-team",
    depends_on_past=False,
    start_date=datetime(2024, 1, 1),
    email_on_failure=False,
    email_on_retry=False,
    retries=1,
    retry_delay=timedelta(minutes=5),
)

MLFLOW_TRACKING_URI = Variable.get("mlflow_tracking_uri", default="http://mlflow:5001")
MODEL_NAME = "churn_predictor"
FEATURES_BUCKET = "features"
PREDICTIONS_BUCKET = "predictions"
AWS_CONN_ID = "minio_s3"


def _s3_read_parquet(bucket, key, aws_conn_id=AWS_CONN_ID):
    hook = S3Hook(aws_conn_id=aws_conn_id)
    obj = hook.get_key(key=key, bucket_name=bucket)
    buf = io.BytesIO(obj.get()["Body"].read())
    return pd.read_parquet(buf)


def _s3_read_pickle(bucket, key, aws_conn_id=AWS_CONN_ID):
    hook = S3Hook(aws_conn_id=aws_conn_id)
    obj = hook.get_key(key=key, bucket_name=bucket)
    return pickle.loads(obj.get()["Body"].read())


def _s3_write_parquet(df: pd.DataFrame, bucket: str, key: str, aws_conn_id=AWS_CONN_ID):
    hook = S3Hook(aws_conn_id=aws_conn_id)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    hook.load_bytes(buf.getvalue(), key=key, bucket_name=bucket, replace=True)
    return f"s3://{bucket}/{key}"


def _gen_synthetic_raw(n: int, ds: str) -> pd.DataFrame:
    np.random.seed(int(ds.replace("-", "")) % (2**31 - 1))
    return pd.DataFrame(
        dict(
            customer_id=[f"SANITY_{i:06d}" for i in range(n)],
            age=np.random.normal(45, 15, n).clip(18, 80).astype(int),
            income=np.random.lognormal(10.5, 0.6, n),
            credit_score=np.random.normal(700, 100, n).clip(300, 850).astype(int),
            account_length_days=np.random.exponential(365, n).astype(int),
            num_products=np.random.poisson(2, n).clip(1, 10),
            total_spend_last_30d=np.random.exponential(500, n),
            num_transactions_last_30d=np.random.poisson(15, n),
            region=np.random.choice(["North", "South", "East", "West"], n),
            customer_segment=np.random.choice(["Premium", "Standard", "Basic"], n, p=[0.2, 0.5, 0.3]),
            has_mobile_app=np.random.choice([True, False], n, p=[0.7, 0.3]),
            email_opens_last_30d=np.random.poisson(5, n),
            support_tickets_last_90d=np.random.poisson(0.5, n),
        )
    )


def load_model_from_registry(**context):
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()

    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    if not versions:
        raise ValueError(f"No versions for model {MODEL_NAME}")

    def _score(v):
        tags = getattr(v, "tags", {}) or {}
        return 1 if tags.get("deployment_status") == "staging" else 0

    chosen = sorted(versions, key=lambda v: (_score(v), int(v.version)), reverse=True)[0]
    run_id = chosen.run_id
    version = int(chosen.version)
    tags = chosen.tags or {}
    data_date = tags.get("data_date")
    if data_date is None:
        run = client.get_run(run_id)
        data_date = run.data.tags.get("data_date")

    model_uri = f"models:/{MODEL_NAME}/{version}"
    pyfunc_model = mlflow.pyfunc.load_model(model_uri)

    signature = pyfunc_model.metadata.signature
    if signature is None or signature.inputs is None:
        raise ValueError("model has no signature")
    input_cols = [c.name for c in signature.inputs.inputs]

    return dict(
        model_uri=model_uri,
        version=version,
        run_id=run_id,
        data_date=data_date,
        input_cols=input_cols,
        deployment_status=tags.get("deployment_status", "unknown"),
    )


def load_new_customers(**context):
    execution_date = context["ds"]
    hook = S3Hook(aws_conn_id=AWS_CONN_ID)
    year, month, day = execution_date.split("-")
    key = f"raw_data/year={year}/month={month}/day={day}/customer_data_{execution_date}.parquet"
    try:
        obj = hook.get_key(key=key, bucket_name=FEATURES_BUCKET)
        buf = io.BytesIO(obj.get()["Body"].read())
        df = pd.read_parquet(buf)
        return df
    except Exception:
        n = 100
        return _gen_synthetic_raw(n, execution_date)


def fetch_scaler_and_schema(**context):
    ti = context["task_instance"]
    model_meta = ti.xcom_pull(task_ids="load_model")
    data_date = model_meta["data_date"]
    if data_date is None:
        raise ValueError("model has no data_date tag")
    year, month, day = data_date.split("-")
    scaler_key = f"prepared_data/year={year}/month={month}/day={day}/scaler.pkl"
    X_train_key = f"prepared_data/year={year}/month={month}/day={day}/X_train.parquet"
    X_train = _s3_read_parquet(FEATURES_BUCKET, X_train_key)
    return dict(
        scaler_key=scaler_key,
        train_columns=X_train.columns.tolist(),
        data_date=data_date,
    )


def _prepare_like_training(df, train_cols, input_cols, scaler):
    ids = df["customer_id"].copy() if "customer_id" in df.columns else pd.Series(range(len(df)))
    if "customer_id" in df.columns:
        df = df.drop(columns=["customer_id"])

    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        df["hour"] = ts.dt.hour
        df["day_of_week"] = ts.dt.dayofweek
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(np.int32)
        df["is_business_hours"] = ((df["hour"] >= 9) & (df["hour"] <= 17)).astype(np.int32)
        df = df.drop(columns=["timestamp"])

    df["spend_per_transaction"] = df["total_spend_last_30d"] / (df["num_transactions_last_30d"] + 1)
    df["avg_product_value"] = df["total_spend_last_30d"] / (df["num_products"] + 1)
    df["engagement_score"] = df["has_mobile_app"].astype(int) * 2 + np.clip(df["email_opens_last_30d"] / 10, 0, 1) * 3
    df["high_support_tickets"] = (df["support_tickets_last_90d"] > 2).astype(np.int32)
    df["low_engagement"] = (df["email_opens_last_30d"] < 2).astype(np.int32)

    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    df = pd.get_dummies(df, columns=cat_cols, drop_first=True)

    # align to training schema
    for c in train_cols:
        if c not in df.columns:
            df[c] = 0.0
    df = df[train_cols]

    # kill infs, fill NaNs, enforce dtype before scaling
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)

    # scale
    X_scaled = scaler.transform(df.values)
    df_scaled = pd.DataFrame(X_scaled, columns=train_cols).astype(np.float32)

    # align to model signature
    for c in input_cols:
        if c not in df_scaled.columns:
            df_scaled[c] = 0.0
    df_scaled = df_scaled[input_cols]

    # final safety net (schema + GBM hates NaNs / wrong dtype)
    df_scaled = df_scaled.replace([np.inf, -np.inf], 0.0).fillna(0.0).astype(np.float32)

    return ids, df_scaled




def prepare_features(**context):
    ti = context["task_instance"]
    raw = ti.xcom_pull(task_ids="load_new_customers")
    model_meta = ti.xcom_pull(task_ids="load_model")
    prep_meta = ti.xcom_pull(task_ids="fetch_scaler_and_schema")

    scaler = _s3_read_pickle(FEATURES_BUCKET, prep_meta["scaler_key"])
    ids, X = _prepare_like_training(raw, prep_meta["train_columns"], model_meta["input_cols"], scaler)

    return dict(X=X, customer_ids=ids.tolist())


def score_customers(**context):
    ti = context["task_instance"]
    model_meta = ti.xcom_pull(task_ids="load_model")
    prepared = ti.xcom_pull(task_ids="prepare_features")

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    model = mlflow.pyfunc.load_model(model_meta["model_uri"])

    preds = model.predict(prepared["X"])
    execution_date = context["ds"]

    out = pd.DataFrame(
        dict(
            customer_id=prepared["customer_ids"],
            churn_probability=preds,
            model_version=model_meta["version"],
            model_stage=model_meta["deployment_status"],
            prediction_date=execution_date,
        )
    )

    out["risk_category"] = pd.cut(
        out["churn_probability"],
        bins=[0, 0.3, 0.7, 1.0],
        labels=["Low Risk", "Medium Risk", "High Risk"],
    )
    return out


def save_predictions(**context):
    ti = context["task_instance"]
    results = ti.xcom_pull(task_ids="score_customers")
    execution_date = context["ds"]

    key = f"predictions/batch/{execution_date}/customer_scores.parquet"
    _s3_write_parquet(results, PREDICTIONS_BUCKET, key)

    summary = dict(
        prediction_date=execution_date,
        total_customers=int(len(results)),
        model_version=int(results["model_version"].iloc[0]),
        model_stage=results["model_stage"].iloc[0],
        risk_distribution=results["risk_category"].value_counts().to_dict(),
        churn_stats=dict(
            mean=float(results["churn_probability"].mean()),
            std=float(results["churn_probability"].std()),
            min=float(results["churn_probability"].min()),
            max=float(results["churn_probability"].max()),
            high_risk_count=int((results["churn_probability"] > 0.7).sum()),
        ),
    )

    hook = S3Hook(aws_conn_id=AWS_CONN_ID)
    hook.load_string(
        string_data=json.dumps(summary, indent=2),
        key=f"predictions/batch/{execution_date}/summary.json",
        bucket_name=PREDICTIONS_BUCKET,
        replace=True,
    )
    return summary


def send_alerts(**context):
    ti = context["task_instance"]
    results = ti.xcom_pull(task_ids="score_customers")
    summary = ti.xcom_pull(task_ids="save_predictions")

    high_risk = results[results["churn_probability"] > 0.7]
    if len(high_risk) > 0:
        print(f"ALERT {len(high_risk)} high risk customers")
        print(high_risk.nlargest(10, "churn_probability")[["customer_id", "churn_probability"]])

    print(
        f"""
Batch prediction summary
total {summary['total_customers']}
model v{summary['model_version']} {summary['model_stage']}
avg churn {summary['churn_stats']['mean']:.4f}
high risk {summary['churn_stats']['high_risk_count']}
"""
    )


def sanity_check_model(**context):
    ti = context["task_instance"]
    model_meta = ti.xcom_pull(task_ids="load_model")
    prep_meta = ti.xcom_pull(task_ids="fetch_scaler_and_schema")
    execution_date = context["ds"]

    # generate small synthetic batch
    raw = _gen_synthetic_raw(n=200, ds=execution_date)

    scaler = _s3_read_pickle(FEATURES_BUCKET, prep_meta["scaler_key"])
    ids, X = _prepare_like_training(raw, prep_meta["train_columns"], model_meta["input_cols"], scaler)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    model = mlflow.pyfunc.load_model(model_meta["model_uri"])
    preds = model.predict(X)

    raw_key = f"predictions/sanity/{execution_date}/raw.parquet"
    preds_key = f"predictions/sanity/{execution_date}/preds.parquet"

    _s3_write_parquet(raw.assign(prediction_date=execution_date), PREDICTIONS_BUCKET, raw_key)

    out = pd.DataFrame(
        dict(
            customer_id=ids,
            churn_probability=preds,
            model_version=model_meta["version"],
            model_stage=model_meta["deployment_status"],
            prediction_date=execution_date,
        )
    )
    _s3_write_parquet(out, PREDICTIONS_BUCKET, preds_key)

    return dict(raw_path=f"s3://{PREDICTIONS_BUCKET}/{raw_key}", preds_path=f"s3://{PREDICTIONS_BUCKET}/{preds_key}")


with DAG(
    dag_id="batch_prediction_pipeline",
    default_args=default_args,
    description="Batch scoring with strict schema alignment and internal sanity check",
    schedule="@weekly",
    catchup=False,
    tags=["prediction", "scoring", "mlflow"],
) as dag:

    load_model = PythonOperator(task_id="load_model", python_callable=load_model_from_registry)
    load_customers = PythonOperator(task_id="load_new_customers", python_callable=load_new_customers)
    fetch_scaler = PythonOperator(task_id="fetch_scaler_and_schema", python_callable=fetch_scaler_and_schema)

    prepare = PythonOperator(task_id="prepare_features", python_callable=prepare_features)
    score = PythonOperator(task_id="score_customers", python_callable=score_customers)
    save = PythonOperator(task_id="save_predictions", python_callable=save_predictions)
    alert = PythonOperator(task_id="send_alerts", python_callable=send_alerts)

    sanity = PythonOperator(task_id="sanity_check_model", python_callable=sanity_check_model)

    [load_model, load_customers] >> fetch_scaler
    fetch_scaler >> prepare >> score >> save >> alert
    fetch_scaler >> sanity
