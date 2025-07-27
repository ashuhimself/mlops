"""
Model Training Pipeline v4
No nested autolog
"""

from datetime import datetime, timedelta
import os
import io
import time
import pickle
import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature

from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
from sklearn.model_selection import cross_val_score

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook

try:
    from airflow.sdk import Variable
except ImportError:
    from airflow.models import Variable

default_args = {
    "owner": "ml_team",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

BUCKET = "features"
AWS_CONN_ID = "minio_s3"

MLFLOW_TRACKING_URI = Variable.get("mlflow_tracking_uri", default="http://mlflow:5001")
EXPERIMENT_NAME = "customer_churn_prediction"
MODEL_NAME = "churn_predictor"

LOCAL_DIR = "/tmp/airflow_model_training_v4"


def safe_log_metrics(d: dict, step: int | None = None):
    if step is None:
        step = int(time.time() * 1000)
    for k, v in d.items():
        mlflow.log_metric(k, float(v), step=step)


def setup_mlflow():
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    os.environ["AWS_ACCESS_KEY_ID"] = "minio"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "minio123"
    os.environ["MLFLOW_S3_ENDPOINT_URL"] = Variable.get("minio_endpoint", default="http://minio:9000")

    client = MlflowClient()
    exp = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if exp is None:
        experiment_id = mlflow.create_experiment(
            EXPERIMENT_NAME,
            tags={"project": "customer_churn", "team": "ml_team", "pipeline": "airflow"},
        )
    else:
        if getattr(exp, "lifecycle_stage", "active") == "deleted":
            client.restore_experiment(exp.experiment_id)
        experiment_id = exp.experiment_id

    mlflow.set_experiment(EXPERIMENT_NAME)
    return experiment_id


MODEL_NAME = "churn_predictor"

def log_model_with_signature(model, X_train, artifact_path: str, register: bool = False):
    input_example = X_train.head(5)
    signature = infer_signature(X_train, model.predict(X_train))
    kwargs = dict(
        sk_model=model,
        artifact_path=artifact_path,        # use artifact_path to avoid the warning
        signature=signature,
        input_example=input_example,
    )
    if register:
        kwargs["registered_model_name"] = MODEL_NAME  # only if you really want to auto-register here
    mlflow.sklearn.log_model(**kwargs)
    return artifact_path



def _date_partition_from_ds(ds: str) -> str:
    year, month, day = ds.split("-")
    return f"year={year}/month={month}/day={day}"


def load_prepared_data(ds: str, **context):
    os.makedirs(LOCAL_DIR, exist_ok=True)

    part = _date_partition_from_ds(ds)
    prefix = f"prepared_data/{part}"
    keys = {
        "X_train": f"{prefix}/X_train.parquet",
        "X_test": f"{prefix}/X_test.parquet",
        "y_train": f"{prefix}/y_train.parquet",
        "y_test": f"{prefix}/y_test.parquet",
        "scaler": f"{prefix}/scaler.pkl",
    }

    s3 = S3Hook(aws_conn_id=AWS_CONN_ID)
    local_paths = {}

    for name, key in keys.items():
        obj = s3.get_key(key=key, bucket_name=BUCKET)
        if obj is None:
            raise FileNotFoundError(f"missing S3 object {key}")
        body = obj.get()["Body"].read()

        if name == "scaler":
            scaler_path = os.path.join(LOCAL_DIR, "scaler.pkl")
            with open(scaler_path, "wb") as f:
                f.write(body)
            local_paths["scaler"] = scaler_path
        else:
            buf = io.BytesIO(body)
            df = pd.read_parquet(buf)
            if name.startswith("y_") and df.shape[1] == 1:
                df = df.iloc[:, 0]
            p = os.path.join(LOCAL_DIR, f"{name}.parquet")
            if isinstance(df, pd.Series):
                df.to_frame().to_parquet(p)
            else:
                df.to_parquet(p)
            local_paths[name] = p

    shapes = {n: pd.read_parquet(local_paths[n]).shape for n in ["X_train", "X_test"]}
    return {
        "local_paths": local_paths,
        "execution_date": ds,
        "shapes": shapes,
    }


def validate_data(**context):
    from pandas.api.types import is_numeric_dtype

    ti = context["task_instance"]
    info = ti.xcom_pull(task_ids="load_prepared_data")
    p = info["local_paths"]

    X_train = pd.read_parquet(p["X_train"])
    X_test = pd.read_parquet(p["X_test"])
    y_train = pd.read_parquet(p["y_train"]).iloc[:, 0]
    y_test = pd.read_parquet(p["y_test"]).iloc[:, 0]

    if X_train.empty or X_test.empty:
        raise ValueError("empty feature matrix")
    if y_train.empty or y_test.empty:
        raise ValueError("empty target series")

    expected_cols = X_train.columns.tolist()
    if list(X_test.columns) != expected_cols:
        raise ValueError("feature columns mismatch between train and test")

    non_numeric_cols = [c for c in X_train.columns if not is_numeric_dtype(X_train[c])]
    if non_numeric_cols:
        raise TypeError(f"Non numeric feature columns found {non_numeric_cols}")

    return {
        "n_features": X_train.shape[1],
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_list": expected_cols,
    }


def _read_local_data(local_paths):
    X_train = pd.read_parquet(local_paths["X_train"])
    X_test = pd.read_parquet(local_paths["X_test"])
    y_train = pd.read_parquet(local_paths["y_train"]).iloc[:, 0]
    y_test = pd.read_parquet(local_paths["y_test"]).iloc[:, 0]
    return X_train, X_test, y_train, y_test


def train_linear_regression(**context):
    ti = context["task_instance"]
    loaded = ti.xcom_pull(task_ids="load_prepared_data")
    X_train, X_test, y_train, y_test = _read_local_data(loaded["local_paths"])

    experiment_id = setup_mlflow()
    model_name = "linear_regression"

    with mlflow.start_run(experiment_id=experiment_id, run_name=model_name) as run:
        mlflow.set_tags(
            {
                "model_type": model_name,
                "data_date": loaded["execution_date"],
                "dag_run_id": context["dag_run"].run_id,
                "model_name": model_name,
            }
        )
        mlflow.sklearn.autolog(log_input_examples=False, silent=True)
        model = LinearRegression()
        model.fit(X_train, y_train)
        mlflow.sklearn.autolog(disable=True)

        y_pred_test = model.predict(X_test)
        test_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_test)))
        test_r2 = float(r2_score(y_test, y_pred_test))
        safe_log_metrics({"test_rmse": test_rmse, "test_r2": test_r2})

        subpath = log_model_with_signature(model, X_train, artifact_path=f"{model_name}_model", register=False)

        return {
            "model_type": model_name,
            "test_rmse": test_rmse,
            "test_r2": test_r2,
            "run_id": run.info.run_id,
            "artifact_subpath": subpath,
        }


def train_random_forest(**context):
    ti = context["task_instance"]
    loaded = ti.xcom_pull(task_ids="load_prepared_data")
    X_train, X_test, y_train, y_test = _read_local_data(loaded["local_paths"])

    experiment_id = setup_mlflow()
    model_name = "random_forest"

    rf_configs = [
        {"n_estimators": 100, "max_depth": 10, "min_samples_split": 5},
        {"n_estimators": 200, "max_depth": 15, "min_samples_split": 10},
        {"n_estimators": 150, "max_depth": None, "min_samples_split": 2},
    ]

    best_rmse = float("inf")
    best_run_id = None
    best_subpath = None

    for i, cfg in enumerate(rf_configs):
        with mlflow.start_run(experiment_id=experiment_id, run_name=f"{model_name}_{i}") as run:
            mlflow.set_tags(
                {
                    "model_type": model_name,
                    "cfg_index": i,
                    "data_date": loaded["execution_date"],
                    "dag_run_id": context["dag_run"].run_id,
                    "model_name": model_name,
                }
            )
            mlflow.sklearn.autolog(log_input_examples=False, silent=True)
            model = RandomForestRegressor(**cfg, random_state=42, n_jobs=-1)
            model.fit(X_train, y_train)
            mlflow.sklearn.autolog(disable=True)

            y_pred_test = model.predict(X_test)
            test_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_test)))
            test_r2 = float(r2_score(y_test, y_pred_test))
            safe_log_metrics({"test_rmse": test_rmse, "test_r2": test_r2})

            subpath = log_model_with_signature(model, X_train, artifact_path=f"{model_name}_model", register=False)

            if test_rmse < best_rmse:
                best_rmse = test_rmse
                best_run_id = run.info.run_id
                best_subpath = subpath

    return {"model_type": model_name, "test_rmse": best_rmse, "run_id": best_run_id, "artifact_subpath": best_subpath}


def train_gradient_boosting(**context):
    ti = context["task_instance"]
    loaded = ti.xcom_pull(task_ids="load_prepared_data")
    X_train, X_test, y_train, y_test = _read_local_data(loaded["local_paths"])

    experiment_id = setup_mlflow()
    model_name = "gradient_boosting"

    params = {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 5, "subsample": 0.8, "random_state": 42}

    with mlflow.start_run(experiment_id=experiment_id, run_name=model_name) as run:
        mlflow.set_tags(
            {
                "model_type": model_name,
                "data_date": loaded["execution_date"],
                "dag_run_id": context["dag_run"].run_id,
                "model_name": model_name,
            }
        )
        mlflow.sklearn.autolog(log_input_examples=False, silent=True)
        model = GradientBoostingRegressor(**params)
        model.fit(X_train, y_train)
        mlflow.sklearn.autolog(disable=True)

        y_pred_test = model.predict(X_test)
        test_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_test)))
        test_r2 = float(r2_score(y_test, y_pred_test))
        safe_log_metrics({"test_rmse": test_rmse, "test_r2": test_r2})

        subpath = log_model_with_signature(model, X_train, artifact_path=f"{model_name}_model", register=False)

        return {
            "model_type": model_name,
            "test_rmse": test_rmse,
            "test_r2": test_r2,
            "run_id": run.info.run_id,
            "artifact_subpath": subpath,
        }


def select_best_model(**context):
    ti = context["task_instance"]

    # pull what actually ran
    candidates = [
        ti.xcom_pull(task_ids="train_linear_regression"),
        ti.xcom_pull(task_ids="train_random_forest"),
        ti.xcom_pull(task_ids="train_gradient_boosting"),
    ]
    candidates = [c for c in candidates if c is not None]

    if not candidates:
        raise ValueError("no candidate models to choose from")

    best = min(candidates, key=lambda x: x["test_rmse"])

    setup_mlflow()
    client = mlflow.tracking.MlflowClient()

    try:
        client.get_registered_model(MODEL_NAME)
    except Exception:
        client.create_registered_model(MODEL_NAME)

    # fallback if some task did not return artifact_subpath
    artifact_subpath = best.get("artifact_subpath")
    if artifact_subpath is None:
        model_path_map = {
            "linear_regression": "linear_regression_model",
            "random_forest": "random_forest_0_model",
            "gradient_boosting": "gradient_boosting_model",
        }
        artifact_subpath = model_path_map[best["model_type"]]

    model_uri = f"runs:/{best['run_id']}/{artifact_subpath}"

    mv = client.create_model_version(
        name=MODEL_NAME,
        source=model_uri,
        run_id=best["run_id"],
        tags={
            "model_type": best["model_type"],
            "test_rmse": str(best["test_rmse"]),
            "status": "ready",
            "deployment_status": "staging",
        },
    )

    # optional but handy
    client.set_model_version_tag(MODEL_NAME, mv.version, "selected_by", "airflow_select_best_model")
    client.set_model_version_tag(MODEL_NAME, mv.version, "airflow_run_id", context["dag_run"].run_id)

    best["registered_version"] = mv.version
    return best



with DAG(
    "model_training_pipeline_v4",
    default_args=default_args,
    description="Train models without nested autolog and signature logging",
    schedule=None,
    catchup=False,
    tags=["mlflow", "training"],
) as dag:

    load_data = PythonOperator(task_id="load_prepared_data", python_callable=load_prepared_data, op_kwargs={"ds": "{{ ds }}"})
    validate = PythonOperator(task_id="validate_data", python_callable=validate_data)
    linear = PythonOperator(task_id="train_linear_regression", python_callable=train_linear_regression)
    rf = PythonOperator(task_id="train_random_forest", python_callable=train_random_forest)
    gb = PythonOperator(task_id="train_gradient_boosting", python_callable=train_gradient_boosting)
    select = PythonOperator(task_id="select_best_model", python_callable=select_best_model, trigger_rule="none_failed_min_one_success")

    load_data >> validate >> [linear, rf, gb] >> select
