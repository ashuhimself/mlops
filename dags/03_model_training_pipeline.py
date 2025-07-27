"""
Model Training Pipeline
=======================
This DAG trains ML models using prepared data, tracks experiments with MLflow,
and supports model retraining. Each run creates a new version of the model
while maintaining the same experiment for comparison.
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import mlflow
import mlflow.sklearn
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression, ElasticNet
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
from sklearn.model_selection import cross_val_score
from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.models import Variable
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
import json
import io
import pickle
import os

default_args = {
    'owner': 'ml-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Configure MLflow
MLFLOW_TRACKING_URI = Variable.get("mlflow_tracking_uri", default_var="http://mlflow:5001")
EXPERIMENT_NAME = "customer_churn_prediction"
MODEL_NAME = "churn_predictor"

def setup_mlflow():
    """Configure MLflow settings."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    
    # Set S3 credentials for artifact storage
    os.environ['AWS_ACCESS_KEY_ID'] = 'minio'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'minio123'
    os.environ['MLFLOW_S3_ENDPOINT_URL'] = Variable.get("minio_endpoint", default_var="http://minio:9000")
    
    # Create or get experiment
    experiment = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        experiment_id = mlflow.create_experiment(
            EXPERIMENT_NAME,
            tags={
                "project": "customer_churn",
                "team": "ml-team",
                "pipeline": "airflow"
            }
        )
    else:
        experiment_id = experiment.experiment_id
    
    return experiment_id

def check_for_new_data(**context):
    """Check if new prepared data is available for training."""
    
    try:
        # Get latest prepared data info
        latest_data = Variable.get("latest_prepared_data", deserialize_json=True)
        
        # Get last trained data info
        last_trained = Variable.get("last_trained_data", default_var=None, deserialize_json=True)
        
        if last_trained is None:
            print("No previous training found. Proceeding with training.")
            return 'load_prepared_data'
        
        if latest_data['execution_date'] > last_trained['execution_date']:
            print(f"New data available: {latest_data['execution_date']} > {last_trained['execution_date']}")
            return 'load_prepared_data'
        else:
            print(f"No new data. Latest: {latest_data['execution_date']}")
            return 'skip_training'
    
    except Exception as e:
        print(f"Error checking for new data: {e}")
        return 'skip_training'

def load_prepared_data(**context):
    """Load prepared datasets from S3."""
    
    # Get data paths
    data_info = Variable.get("latest_prepared_data", deserialize_json=True)
    paths = data_info['paths']
    
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Load datasets
    datasets = {}
    
    for name in ['X_train', 'X_test', 'y_train', 'y_test']:
        key = paths[name].replace('s3://features/', '')
        obj = s3_hook.get_key(key=key, bucket_name='features')
        buffer = io.BytesIO(obj.get()['Body'].read())
        
        df = pd.read_parquet(buffer)
        
        # Convert single column dataframes back to series
        if name.startswith('y_') and df.shape[1] == 1:
            datasets[name] = df.iloc[:, 0]
        else:
            datasets[name] = df
        
        print(f"Loaded {name}: shape = {datasets[name].shape}")
    
    # Load scaler
    scaler_key = paths['scaler'].replace('s3://features/', '')
    obj = s3_hook.get_key(key=scaler_key, bucket_name='features')
    scaler = pickle.loads(obj.get()['Body'].read())
    
    # Load metadata
    metadata_key = paths['metadata'].replace('s3://features/', '')
    metadata_str = s3_hook.read_key(key=metadata_key, bucket_name='features')
    metadata = json.loads(metadata_str)
    
    return {
        'X_train': datasets['X_train'],
        'X_test': datasets['X_test'],
        'y_train': datasets['y_train'],
        'y_test': datasets['y_test'],
        'scaler': scaler,
        'metadata': metadata,
        'data_info': data_info
    }

def train_baseline_model(**context):
    """Train a baseline linear regression model."""
    
    ti = context['task_instance']
    data = ti.xcom_pull(task_ids='load_prepared_data')
    
    X_train = data['X_train']
    X_test = data['X_test']
    y_train = data['y_train']
    y_test = data['y_test']
    
    experiment_id = setup_mlflow()
    
    with mlflow.start_run(experiment_id=experiment_id, run_name="baseline_linear_regression"):
        # Log data info
        mlflow.log_param("model_type", "linear_regression")
        mlflow.log_param("data_date", data['data_info']['execution_date'])
        mlflow.log_param("n_features", X_train.shape[1])
        mlflow.log_param("n_train_samples", len(X_train))
        
        # Train model
        print("Training baseline Linear Regression model...")
        model = LinearRegression()
        model.fit(X_train, y_train)
        
        # Make predictions
        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)
        
        # Calculate metrics
        train_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
        test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))
        train_r2 = r2_score(y_train, y_pred_train)
        test_r2 = r2_score(y_test, y_pred_test)
        train_mae = mean_absolute_error(y_train, y_pred_train)
        test_mae = mean_absolute_error(y_test, y_pred_test)
        
        # Log metrics
        mlflow.log_metric("train_rmse", train_rmse)
        mlflow.log_metric("test_rmse", test_rmse)
        mlflow.log_metric("train_r2", train_r2)
        mlflow.log_metric("test_r2", test_r2)
        mlflow.log_metric("train_mae", train_mae)
        mlflow.log_metric("test_mae", test_mae)
        
        # Log model
        mlflow.sklearn.log_model(
            model,
            "model",
            input_example=X_train.iloc[:5]
        )
        
        print(f"Baseline model - Test RMSE: {test_rmse:.4f}, Test R²: {test_r2:.4f}")
        
        return {
            'model_type': 'linear_regression',
            'test_rmse': test_rmse,
            'test_r2': test_r2,
            'run_id': mlflow.active_run().info.run_id
        }

def train_random_forest(**context):
    """Train a Random Forest model with hyperparameter tuning."""
    
    ti = context['task_instance']
    data = ti.xcom_pull(task_ids='load_prepared_data')
    
    X_train = data['X_train']
    X_test = data['X_test']
    y_train = data['y_train']
    y_test = data['y_test']
    
    experiment_id = setup_mlflow()
    
    # Hyperparameter configurations to try
    rf_configs = [
        {'n_estimators': 100, 'max_depth': 10, 'min_samples_split': 5},
        {'n_estimators': 200, 'max_depth': 15, 'min_samples_split': 10},
        {'n_estimators': 150, 'max_depth': None, 'min_samples_split': 2}
    ]
    
    best_model = None
    best_rmse = float('inf')
    best_run_id = None
    
    for config in rf_configs:
        with mlflow.start_run(experiment_id=experiment_id, run_name=f"random_forest_{config['n_estimators']}"):
            # Log parameters
            mlflow.log_param("model_type", "random_forest")
            mlflow.log_param("data_date", data['data_info']['execution_date'])
            mlflow.log_param("n_features", X_train.shape[1])
            mlflow.log_param("n_train_samples", len(X_train))
            
            for param, value in config.items():
                mlflow.log_param(param, value)
            
            # Train model
            print(f"Training Random Forest with config: {config}")
            model = RandomForestRegressor(
                **config,
                random_state=42,
                n_jobs=-1
            )
            
            # Cross-validation
            cv_scores = cross_val_score(
                model, X_train, y_train, 
                cv=5, scoring='neg_mean_squared_error'
            )
            cv_rmse = np.sqrt(-cv_scores.mean())
            mlflow.log_metric("cv_rmse", cv_rmse)
            
            # Fit model
            model.fit(X_train, y_train)
            
            # Make predictions
            y_pred_train = model.predict(X_train)
            y_pred_test = model.predict(X_test)
            
            # Calculate metrics
            train_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
            test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))
            train_r2 = r2_score(y_train, y_pred_train)
            test_r2 = r2_score(y_test, y_pred_test)
            
            # Log metrics
            mlflow.log_metric("train_rmse", train_rmse)
            mlflow.log_metric("test_rmse", test_rmse)
            mlflow.log_metric("train_r2", train_r2)
            mlflow.log_metric("test_r2", test_r2)
            
            # Log feature importance
            feature_importance = pd.DataFrame({
                'feature': X_train.columns,
                'importance': model.feature_importances_
            }).sort_values('importance', ascending=False)
            
            # Save feature importance as artifact
            importance_path = '/tmp/feature_importance.csv'
            feature_importance.to_csv(importance_path, index=False)
            mlflow.log_artifact(importance_path)
            
            # Log model
            mlflow.sklearn.log_model(
                model,
                "model",
                input_example=X_train.iloc[:5]
            )
            
            print(f"Random Forest - Test RMSE: {test_rmse:.4f}, Test R²: {test_r2:.4f}")
            
            # Track best model
            if test_rmse < best_rmse:
                best_rmse = test_rmse
                best_model = model
                best_run_id = mlflow.active_run().info.run_id
    
    return {
        'model_type': 'random_forest',
        'test_rmse': best_rmse,
        'run_id': best_run_id
    }

def train_gradient_boosting(**context):
    """Train a Gradient Boosting model."""
    
    ti = context['task_instance']
    data = ti.xcom_pull(task_ids='load_prepared_data')
    
    X_train = data['X_train']
    X_test = data['X_test']
    y_train = data['y_train']
    y_test = data['y_test']
    
    experiment_id = setup_mlflow()
    
    with mlflow.start_run(experiment_id=experiment_id, run_name="gradient_boosting"):
        # Log parameters
        mlflow.log_param("model_type", "gradient_boosting")
        mlflow.log_param("data_date", data['data_info']['execution_date'])
        mlflow.log_param("n_features", X_train.shape[1])
        mlflow.log_param("n_train_samples", len(X_train))
        
        # Model parameters
        params = {
            'n_estimators': 100,
            'learning_rate': 0.1,
            'max_depth': 5,
            'subsample': 0.8,
            'random_state': 42
        }
        
        for param, value in params.items():
            mlflow.log_param(param, value)
        
        # Train model
        print("Training Gradient Boosting model...")
        model = GradientBoostingRegressor(**params)
        model.fit(X_train, y_train)
        
        # Make predictions
        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)
        
        # Calculate metrics
        train_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
        test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))
        train_r2 = r2_score(y_train, y_pred_train)
        test_r2 = r2_score(y_test, y_pred_test)
        
        # Log metrics
        mlflow.log_metric("train_rmse", train_rmse)
        mlflow.log_metric("test_rmse", test_rmse)
        mlflow.log_metric("train_r2", train_r2)
        mlflow.log_metric("test_r2", test_r2)
        
        # Log model
        mlflow.sklearn.log_model(
            model,
            "model",
            input_example=X_train.iloc[:5]
        )
        
        print(f"Gradient Boosting - Test RMSE: {test_rmse:.4f}, Test R²: {test_r2:.4f}")
        
        return {
            'model_type': 'gradient_boosting',
            'test_rmse': test_rmse,
            'test_r2': test_r2,
            'run_id': mlflow.active_run().info.run_id
        }

def select_best_model(**context):
    """Select the best model based on performance and register it."""
    
    ti = context['task_instance']
    
    # Get results from all models
    baseline_results = ti.xcom_pull(task_ids='train_baseline_model')
    rf_results = ti.xcom_pull(task_ids='train_random_forest')
    gb_results = ti.xcom_pull(task_ids='train_gradient_boosting')
    
    # Compare models
    models = [baseline_results, rf_results, gb_results]
    best_model = min(models, key=lambda x: x['test_rmse'])
    
    print(f"Best model: {best_model['model_type']} with RMSE: {best_model['test_rmse']:.4f}")
    
    # Register the best model
    setup_mlflow()
    
    try:
        # Check if model is already registered
        client = mlflow.tracking.MlflowClient()
        try:
            registered_model = client.get_registered_model(MODEL_NAME)
            print(f"Model '{MODEL_NAME}' already exists. Creating new version.")
        except:
            print(f"Creating new registered model '{MODEL_NAME}'")
            client.create_registered_model(
                MODEL_NAME,
                tags={
                    "task": "churn_prediction",
                    "team": "ml-team"
                },
                description="Customer churn prediction model"
            )
        
        # Register the best model version
        model_uri = f"runs:/{best_model['run_id']}/model"
        model_version = client.create_model_version(
            name=MODEL_NAME,
            source=model_uri,
            run_id=best_model['run_id'],
            tags={
                "model_type": best_model['model_type'],
                "test_rmse": str(best_model['test_rmse'])
            }
        )
        
        print(f"Registered model version: {model_version.version}")
        
        # Transition to staging
        client.transition_model_version_stage(
            name=MODEL_NAME,
            version=model_version.version,
            stage="Staging"
        )
        
    except Exception as e:
        print(f"Error registering model: {e}")
    
    # Update last trained data
    data_info = ti.xcom_pull(task_ids='load_prepared_data')['data_info']
    Variable.set(
        key="last_trained_data",
        value=json.dumps({
            'execution_date': data_info['execution_date'],
            'best_model': best_model,
            'timestamp': datetime.now().isoformat()
        })
    )
    
    return best_model

def skip_training(**context):
    """Skip training when no new data is available."""
    print("Skipping training - no new data available")
    return "No new data"

with DAG(
    '03_model_training_pipeline',
    default_args=default_args,
    description='Train and retrain ML models with MLflow tracking',
    schedule=None,  # Triggered manually or by data preparation pipeline
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['model-training', 'ml-pipeline', 'mlflow'],
    doc_md=__doc__
) as dag:
    
    # Check for new data
    check_data = BranchPythonOperator(
        task_id='check_for_new_data',
        python_callable=check_for_new_data,
        doc_md="Check if new prepared data is available"
    )
    
    # Skip path
    skip = PythonOperator(
        task_id='skip_training',
        python_callable=skip_training,
        doc_md="Skip training when no new data"
    )
    
    # Load data
    load_data = PythonOperator(
        task_id='load_prepared_data',
        python_callable=load_prepared_data,
        doc_md="Load prepared datasets from S3"
    )
    
    # Train models
    baseline_model = PythonOperator(
        task_id='train_baseline_model',
        python_callable=train_baseline_model,
        doc_md="Train baseline linear regression model"
    )
    
    rf_model = PythonOperator(
        task_id='train_random_forest',
        python_callable=train_random_forest,
        doc_md="Train Random Forest models with different configs"
    )
    
    gb_model = PythonOperator(
        task_id='train_gradient_boosting',
        python_callable=train_gradient_boosting,
        doc_md="Train Gradient Boosting model"
    )
    
    # Select best model
    select_best = PythonOperator(
        task_id='select_best_model',
        python_callable=select_best_model,
        doc_md="Select and register the best performing model",
        trigger_rule='none_failed_min_one_success'
    )
    
    # Define dependencies
    check_data >> [load_data, skip]
    load_data >> [baseline_model, rf_model, gb_model] >> select_best 