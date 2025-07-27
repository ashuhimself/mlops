"""
Batch Prediction Pipeline
=========================
This DAG performs batch predictions using the latest model from MLflow.
Can be scheduled to run daily/weekly for scoring new customers.
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import mlflow
import mlflow.sklearn
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.models import Variable
import json
import io
import pickle

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
MODEL_NAME = "churn_predictor"

def load_model_from_registry(**context):
    """Load the latest model from MLflow Model Registry."""
    
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()
    
    # Get latest model version in staging or production
    versions = client.get_latest_versions(MODEL_NAME, stages=["Production"])
    if not versions:
        versions = client.get_latest_versions(MODEL_NAME, stages=["Staging"])
    
    if not versions:
        raise ValueError(f"No staging/production versions found for model {MODEL_NAME}")
    
    latest_version = versions[0]
    model_uri = f"models:/{MODEL_NAME}/{latest_version.version}"
    
    print(f"Loading model {MODEL_NAME} version {latest_version.version} (stage: {latest_version.current_stage})")
    model = mlflow.sklearn.load_model(model_uri)
    
    return {
        'model': model,
        'version': latest_version.version,
        'stage': latest_version.current_stage
    }

def load_new_customers(**context):
    """Load new customer data for scoring."""
    
    execution_date = context['ds']
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # In a real scenario, this would load actual new customer data
    # For demo, we'll load the latest raw data
    year, month, day = execution_date.split('-')
    key = f"raw_data/year={year}/month={month}/day={day}/customer_data_{execution_date}.parquet"
    
    try:
        obj = s3_hook.get_key(key=key, bucket_name='features')
        buffer = io.BytesIO(obj.get()['Body'].read())
        data = pd.read_parquet(buffer)
        
        print(f"Loaded {len(data)} customers for scoring")
        return data
    except:
        # If no data for today, generate some sample data
        print("No new data found, generating sample customers...")
        n_customers = 100
        data = pd.DataFrame({
            'customer_id': [f'NEW_{i:06d}' for i in range(n_customers)],
            'age': np.random.normal(45, 15, n_customers).clip(18, 80).astype(int),
            'income': np.random.lognormal(10.5, 0.6, n_customers),
            'credit_score': np.random.normal(700, 100, n_customers).clip(300, 850).astype(int),
            'account_length_days': np.random.exponential(365, n_customers).astype(int),
            'num_products': np.random.poisson(2, n_customers).clip(1, 10),
            'total_spend_last_30d': np.random.exponential(500, n_customers),
            'num_transactions_last_30d': np.random.poisson(15, n_customers),
            'region': np.random.choice(['North', 'South', 'East', 'West'], n_customers),
            'customer_segment': np.random.choice(['Premium', 'Standard', 'Basic'], 
                                               n_customers, p=[0.2, 0.5, 0.3]),
            'has_mobile_app': np.random.choice([True, False], n_customers, p=[0.7, 0.3]),
            'email_opens_last_30d': np.random.poisson(5, n_customers),
            'support_tickets_last_90d': np.random.poisson(0.5, n_customers),
        })
        return data

def prepare_features(**context):
    """Prepare features for prediction."""
    
    ti = context['task_instance']
    data = ti.xcom_pull(task_ids='load_new_customers')
    
    # Apply same feature engineering as training
    df = data.copy()
    
    # Time features (if timestamp exists)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        df['is_business_hours'] = ((df['hour'] >= 9) & (df['hour'] <= 17)).astype(int)
    
    # Customer behavior features
    df['spend_per_transaction'] = df['total_spend_last_30d'] / (df['num_transactions_last_30d'] + 1)
    df['avg_product_value'] = df['total_spend_last_30d'] / (df['num_products'] + 1)
    df['engagement_score'] = (
        df['has_mobile_app'].astype(int) * 2 + 
        np.clip(df['email_opens_last_30d'] / 10, 0, 1) * 3
    )
    
    # Risk indicators
    df['high_support_tickets'] = (df['support_tickets_last_90d'] > 2).astype(int)
    df['low_engagement'] = (df['email_opens_last_30d'] < 2).astype(int)
    
    # Handle missing values
    numerical_cols = df.select_dtypes(include=[np.number]).columns
    for col in numerical_cols:
        if df[col].isnull().any():
            df[col].fillna(df[col].median(), inplace=True)
    
    return df

def score_customers(**context):
    """Score customers using the loaded model."""
    
    ti = context['task_instance']
    model_info = ti.xcom_pull(task_ids='load_model')
    df = ti.xcom_pull(task_ids='prepare_features')
    
    # Load the preprocessor/scaler if available
    execution_date = context['ds']
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Prepare features for model
    feature_cols = [col for col in df.columns if col not in [
        'customer_id', 'timestamp', 'churn_probability'
    ]]
    
    # Separate numerical and categorical
    numerical_features = df[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
    categorical_features = df[feature_cols].select_dtypes(include=['object', 'category']).columns.tolist()
    
    # Keep customer IDs for later
    customer_ids = df['customer_id'].values
    
    # One-hot encode
    df_encoded = pd.get_dummies(
        df,
        columns=categorical_features,
        prefix=categorical_features,
        drop_first=True
    )
    
    # Select feature columns
    feature_cols_encoded = [col for col in df_encoded.columns if col not in [
        'customer_id', 'timestamp', 'churn_probability'
    ]]
    
    X = df_encoded[feature_cols_encoded]
    
    # Note: In production, you'd load the exact scaler used during training
    # For now, we'll standardize the numerical features
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X[numerical_features] = scaler.fit_transform(X[numerical_features])
    
    # Make predictions
    # The model_info contains a serialized model, but in XCom it's just metadata
    # So we need to reload the model
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    model_uri = f"models:/{MODEL_NAME}/{model_info['version']}"
    model = mlflow.sklearn.load_model(model_uri)
    
    predictions = model.predict(X)
    
    # Create results DataFrame
    results = pd.DataFrame({
        'customer_id': customer_ids,
        'churn_probability': predictions,
        'model_version': model_info['version'],
        'model_stage': model_info['stage'],
        'prediction_date': execution_date
    })
    
    # Add risk categories
    results['risk_category'] = pd.cut(
        results['churn_probability'],
        bins=[0, 0.3, 0.7, 1.0],
        labels=['Low Risk', 'Medium Risk', 'High Risk']
    )
    
    print(f"Scored {len(results)} customers")
    print(f"Risk distribution:\n{results['risk_category'].value_counts()}")
    
    return results

def save_predictions(**context):
    """Save predictions to S3."""
    
    ti = context['task_instance']
    results = ti.xcom_pull(task_ids='score_customers')
    execution_date = context['ds']
    
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Save predictions
    buffer = io.BytesIO()
    results.to_parquet(buffer, index=False)
    
    key = f"predictions/batch/{execution_date}/customer_scores.parquet"
    s3_hook.load_bytes(
        bytes_data=buffer.getvalue(),
        key=key,
        bucket_name='predictions',
        replace=True
    )
    
    print(f"Saved predictions to s3://predictions/{key}")
    
    # Also save summary statistics
    summary = {
        'prediction_date': execution_date,
        'total_customers': len(results),
        'model_version': results['model_version'].iloc[0],
        'model_stage': results['model_stage'].iloc[0],
        'risk_distribution': results['risk_category'].value_counts().to_dict(),
        'churn_stats': {
            'mean': float(results['churn_probability'].mean()),
            'std': float(results['churn_probability'].std()),
            'min': float(results['churn_probability'].min()),
            'max': float(results['churn_probability'].max()),
            'high_risk_count': int((results['churn_probability'] > 0.7).sum())
        }
    }
    
    summary_key = f"predictions/batch/{execution_date}/summary.json"
    s3_hook.load_string(
        string_data=json.dumps(summary, indent=2),
        key=summary_key,
        bucket_name='predictions',
        replace=True
    )
    
    return summary

def send_alerts(**context):
    """Send alerts for high-risk customers."""
    
    ti = context['task_instance']
    results = ti.xcom_pull(task_ids='score_customers')
    summary = ti.xcom_pull(task_ids='save_predictions')
    
    high_risk_customers = results[results['churn_probability'] > 0.7]
    
    if len(high_risk_customers) > 0:
        print(f"⚠️ ALERT: {len(high_risk_customers)} high-risk customers identified!")
        print("\nTop 10 highest risk customers:")
        print(high_risk_customers.nlargest(10, 'churn_probability')[['customer_id', 'churn_probability']])
        
        # In production, this would send actual alerts (email, Slack, etc.)
        # For now, we'll just log the information
        
    print(f"\nBatch prediction summary:")
    print(f"- Total customers scored: {summary['total_customers']}")
    print(f"- Model version: {summary['model_version']} ({summary['model_stage']})")
    print(f"- Average churn probability: {summary['churn_stats']['mean']:.3f}")
    print(f"- High risk customers: {summary['churn_stats']['high_risk_count']}")

with DAG(
    'batch_prediction_pipeline',
    default_args=default_args,
    description='Batch scoring of customers using latest ML model',
    schedule='@weekly',  # Run weekly
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['prediction', 'scoring', 'ml-pipeline'],
    doc_md=__doc__
) as dag:
    
    load_model = PythonOperator(
        task_id='load_model',
        python_callable=load_model_from_registry,
        doc_md="Load latest model from MLflow registry"
    )
    
    load_customers = PythonOperator(
        task_id='load_new_customers',
        python_callable=load_new_customers,
        doc_md="Load new customer data for scoring"
    )
    
    prepare = PythonOperator(
        task_id='prepare_features',
        python_callable=prepare_features,
        doc_md="Prepare features for prediction"
    )
    
    score = PythonOperator(
        task_id='score_customers',
        python_callable=score_customers,
        doc_md="Score customers using ML model"
    )
    
    save = PythonOperator(
        task_id='save_predictions',
        python_callable=save_predictions,
        doc_md="Save predictions to S3"
    )
    
    alert = PythonOperator(
        task_id='send_alerts',
        python_callable=send_alerts,
        doc_md="Send alerts for high-risk customers"
    )
    
    # Dependencies
    [load_model, load_customers] >> prepare >> score >> save >> alert 