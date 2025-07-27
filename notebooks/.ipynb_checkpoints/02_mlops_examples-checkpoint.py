#!/usr/bin/env python3
"""
MLOps Examples Notebook
=======================
This notebook contains examples of using:
1. MinIO S3 for data storage
2. MLflow for experiment tracking
3. Data processing pipelines
4. Model training and tracking
"""

import boto3
import pandas as pd
import numpy as np
import mlflow
import os
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import matplotlib.pyplot as plt
import seaborn as sns

# %% [markdown]
# ## 1. Setup Configuration

# Configure S3 client
s3_client = boto3.client(
    's3',
    endpoint_url='http://minio:9000',
    aws_access_key_id='minio',
    aws_secret_access_key='minio123'
)

# Configure MLflow
mlflow.set_tracking_uri('http://mlflow:5001')
os.environ['MLFLOW_S3_ENDPOINT_URL'] = 'http://minio:9000'
os.environ['AWS_ACCESS_KEY_ID'] = 'minio'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'minio123'

print("Configuration completed!")
print(f"MLflow tracking URI: {mlflow.get_tracking_uri()}")

# %% [markdown]
# ## 2. Generate Sample Dataset

# Generate synthetic data
np.random.seed(42)
n_samples = 1000

data = pd.DataFrame({
    'feature_1': np.random.normal(100, 15, n_samples),
    'feature_2': np.random.exponential(2, n_samples),
    'feature_3': np.random.uniform(0, 100, n_samples),
    'category': np.random.choice(['A', 'B', 'C', 'D'], n_samples),
    'timestamp': pd.date_range(start='2024-01-01', periods=n_samples, freq='H')
})

# Create target variable with some relationship to features
data['target'] = (
    0.5 * data['feature_1'] + 
    2.0 * data['feature_2'] + 
    0.1 * data['feature_3'] +
    np.random.normal(0, 5, n_samples)
)

print("Dataset shape:", data.shape)
print("\nFirst 5 rows:")
print(data.head())

# %% [markdown]
# ## 3. Save Data to S3

# Save raw data to S3
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
raw_data_key = f"data/raw/synthetic_data_{timestamp}.parquet"

# Convert to parquet and upload
data.to_parquet('/tmp/temp_data.parquet', index=False)
with open('/tmp/temp_data.parquet', 'rb') as f:
    s3_client.put_object(
        Bucket='features',
        Key=raw_data_key,
        Body=f
    )

print(f"✅ Raw data saved to s3://features/{raw_data_key}")

# %% [markdown]
# ## 4. Feature Engineering

# One-hot encode categorical features
data_encoded = pd.get_dummies(data, columns=['category'], prefix='category')

# Create time-based features
data_encoded['hour'] = data_encoded['timestamp'].dt.hour
data_encoded['day_of_week'] = data_encoded['timestamp'].dt.dayofweek
data_encoded['is_weekend'] = (data_encoded['day_of_week'] >= 5).astype(int)

# Drop timestamp for modeling
features = data_encoded.drop(['timestamp', 'target'], axis=1)
target = data_encoded['target']

print("Features shape after encoding:", features.shape)
print("\nFeature columns:")
print(features.columns.tolist())

# %% [markdown]
# ## 5. Train Model with MLflow Tracking

# Create or get experiment
experiment_name = "jupyter_ml_experiment"
experiment = mlflow.get_experiment_by_name(experiment_name)
if experiment is None:
    experiment_id = mlflow.create_experiment(
        experiment_name,
        tags={"environment": "jupyter", "project": "mlops_demo"}
    )
else:
    experiment_id = experiment.experiment_id

print(f"Using experiment: {experiment_name} (ID: {experiment_id})")

# Split data
X_train, X_test, y_train, y_test = train_test_split(
    features, target, test_size=0.2, random_state=42
)

# Train model with MLflow tracking
with mlflow.start_run(experiment_id=experiment_id, run_name="rf_model_jupyter"):
    # Log parameters
    n_estimators = 100
    max_depth = 10
    min_samples_split = 5
    
    mlflow.log_param("n_estimators", n_estimators)
    mlflow.log_param("max_depth", max_depth)
    mlflow.log_param("min_samples_split", min_samples_split)
    mlflow.log_param("n_features", X_train.shape[1])
    mlflow.log_param("n_samples_train", X_train.shape[0])
    
    # Train model
    print("Training Random Forest model...")
    rf_model = RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_split=min_samples_split,
        random_state=42
    )
    rf_model.fit(X_train, y_train)
    
    # Make predictions
    y_pred_train = rf_model.predict(X_train)
    y_pred_test = rf_model.predict(X_test)
    
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
    
    print(f"Train RMSE: {train_rmse:.2f}")
    print(f"Test RMSE: {test_rmse:.2f}")
    print(f"Train R²: {train_r2:.3f}")
    print(f"Test R²: {test_r2:.3f}")
    
    # Create and log feature importance plot
    plt.figure(figsize=(10, 6))
    feature_importance = pd.DataFrame({
        'feature': features.columns,
        'importance': rf_model.feature_importances_
    }).sort_values('importance', ascending=False).head(10)
    
    sns.barplot(data=feature_importance, x='importance', y='feature')
    plt.title('Top 10 Feature Importances')
    plt.tight_layout()
    plt.savefig('/tmp/feature_importance.png')
    mlflow.log_artifact('/tmp/feature_importance.png')
    plt.close()
    
    # Log the model
    mlflow.sklearn.log_model(
        rf_model, 
        "random_forest_model",
        input_example=X_train.iloc[:5]
    )
    
    # Save predictions to S3
    predictions_df = pd.DataFrame({
        'actual': y_test,
        'predicted': y_pred_test,
        'error': y_test - y_pred_test
    })
    
    pred_key = f"predictions/rf_predictions_{timestamp}.csv"
    predictions_csv = predictions_df.to_csv(index=False)
    s3_client.put_object(
        Bucket='models',
        Key=pred_key,
        Body=predictions_csv
    )
    mlflow.log_param("predictions_s3_path", f"s3://models/{pred_key}")
    
    run_id = mlflow.active_run().info.run_id
    print(f"\n✅ MLflow run completed: {run_id}")

# %% [markdown]
# ## 6. List Recent Experiments and Runs

# List recent runs
runs = mlflow.search_runs(experiment_ids=[experiment_id], max_results=5)
print("\nRecent MLflow runs:")
print(runs[['run_id', 'start_time', 'metrics.test_rmse', 'metrics.test_r2']].to_string(index=False))

# %% [markdown]
# ## 7. List S3 Objects Created

# List objects in features bucket
print("\nObjects in s3://features/:")
response = s3_client.list_objects_v2(Bucket='features', MaxKeys=10)
if 'Contents' in response:
    for obj in response['Contents'][-5:]:
        print(f"  - {obj['Key']} ({obj['Size']} bytes)")

# List objects in models bucket
print("\nObjects in s3://models/:")
response = s3_client.list_objects_v2(Bucket='models', MaxKeys=10)
if 'Contents' in response:
    for obj in response['Contents'][-5:]:
        print(f"  - {obj['Key']} ({obj['Size']} bytes)")

print("\n" + "="*50)
print("✅ MLOps workflow completed successfully!")
print("="*50)
print("\nNext steps:")
print("1. View experiment in MLflow UI: http://localhost:5001")
print("2. Browse S3 objects in MinIO: http://localhost:9001")
print("3. Create Airflow DAG to automate this workflow") 