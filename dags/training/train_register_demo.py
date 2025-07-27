"""
Validation DAG to test MLOps infrastructure
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import os
import mlflow
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

default_args = {
    'owner': 'mlops-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'train_register_demo',
    default_args=default_args,
    description='Demo DAG to validate MLOps infrastructure',
    schedule=None,
    catchup=False,
    tags=['training', 'demo'],
)

def train_and_register_model(**context):
    """Generate synthetic data, train model, and register with MLflow"""
    
    # Set MLflow tracking URI from environment
    mlflow.set_tracking_uri(os.environ.get('MLFLOW_TRACKING_URI', 'http://mlflow:5001'))
    
    # Create or get experiment
    experiment_name = "demo-exp"
    experiment = mlflow.set_experiment(experiment_name)
    
    print(f"MLflow tracking URI: {mlflow.get_tracking_uri()}")
    print(f"Experiment: {experiment_name} (ID: {experiment.experiment_id})")
    
    # Generate synthetic data
    np.random.seed(42)
    n_samples = 1000
    n_features = 5
    
    X = np.random.randn(n_samples, n_features)
    true_coefficients = np.array([1.5, -2.0, 0.5, 3.0, -1.0])
    y = X.dot(true_coefficients) + np.random.randn(n_samples) * 0.5
    
    # Create DataFrame for better logging
    feature_names = [f"feature_{i}" for i in range(n_features)]
    df = pd.DataFrame(X, columns=feature_names)
    df['target'] = y
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Start MLflow run
    with mlflow.start_run(run_name=f"demo_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"):
        # Log parameters
        mlflow.log_param("n_samples", n_samples)
        mlflow.log_param("n_features", n_features)
        mlflow.log_param("test_size", 0.2)
        mlflow.log_param("random_state", 42)
        
        # Train model
        model = LinearRegression()
        model.fit(X_train, y_train)
        
        # Make predictions
        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)
        
        # Calculate metrics
        train_mse = mean_squared_error(y_train, y_pred_train)
        test_mse = mean_squared_error(y_test, y_pred_test)
        train_r2 = r2_score(y_train, y_pred_train)
        test_r2 = r2_score(y_test, y_pred_test)
        
        # Log metrics
        mlflow.log_metric("train_mse", train_mse)
        mlflow.log_metric("test_mse", test_mse)
        mlflow.log_metric("train_r2", train_r2)
        mlflow.log_metric("test_r2", test_r2)
        
        # Log model coefficients as metrics
        for i, coef in enumerate(model.coef_):
            mlflow.log_metric(f"coefficient_{i}", coef)
        mlflow.log_metric("intercept", model.intercept_)
        
        # Log the model
        mlflow.sklearn.log_model(
            model,
            "linear_regression_model",
            registered_model_name="demo_linear_regression",
            input_example=X_train[:5],
        )
        
        # Log sample data as artifact
        sample_df = df.head(100)
        sample_df.to_csv("/tmp/sample_data.csv", index=False)
        mlflow.log_artifact("/tmp/sample_data.csv", "data")
        
        run_id = mlflow.active_run().info.run_id
        print(f"MLflow run completed. Run ID: {run_id}")
        print(f"Metrics - Train MSE: {train_mse:.4f}, Test MSE: {test_mse:.4f}")
        print(f"Metrics - Train R2: {train_r2:.4f}, Test R2: {test_r2:.4f}")
        
    return {
        "experiment_name": experiment_name,
        "run_id": run_id,
        "metrics": {
            "train_mse": train_mse,
            "test_mse": test_mse,
            "train_r2": train_r2,
            "test_r2": test_r2
        }
    }

# Define task
train_task = PythonOperator(
    task_id='train_and_register_model',
    python_callable=train_and_register_model,
    dag=dag,
)
