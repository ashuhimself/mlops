# ML Pipeline Guide: Data Generation, Preparation, and Model Retraining

## 📊 Overview

This guide explains the three-stage ML pipeline system for automated model training and retraining:

1. **Data Generation Pipeline** - Simulates new data arriving daily
2. **Data Preparation Pipeline** - Feature engineering and data preprocessing
3. **Model Training Pipeline** - Training, evaluation, and model versioning

## 🔄 Pipeline Architecture

```
┌─────────────────────┐
│  Data Generation    │  (Runs Daily)
│  Pipeline           │
└──────────┬──────────┘
           │
           v
┌─────────────────────┐
│  Data Preparation   │  (Triggered by Data Generation)
│  Pipeline           │
└──────────┬──────────┘
           │
           v
┌─────────────────────┐
│  Model Training     │  (Manual or Triggered)
│  Pipeline           │
└─────────────────────┘
```

## 📁 Pipeline Details

### 1. Data Generation Pipeline (`01_data_generation_pipeline`)

**Purpose**: Generates synthetic customer data to simulate real-world data arrival

**Schedule**: Daily (`@daily`)

**Key Features**:
- Generates 800-1300 records daily with realistic customer attributes
- Includes data quality issues (5% missing values, 2% outliers)
- Saves to S3 with date partitioning: `s3://features/raw_data/year=YYYY/month=MM/day=DD/`
- Performs data validation and quality scoring

**Output**:
- Raw customer data (Parquet format)
- Data quality validation report (JSON)

### 2. Data Preparation Pipeline (`02_data_preparation_pipeline`)

**Purpose**: Transforms raw data into ML-ready features

**Schedule**: Triggered after data generation completes

**Key Features**:
- **Feature Engineering**:
  - Time-based features (hour, day_of_week, is_weekend)
  - Customer behavior metrics (spend_per_transaction, engagement_score)
  - Risk indicators (high_support_tickets, low_engagement)
  - Segment-based comparisons
- **Data Cleaning**:
  - Handles missing values (median for numeric, mode for categorical)
  - Caps outliers using IQR method
- **Data Splitting**:
  - 80/20 train/test split
  - Stratified by target variable
- **Feature Scaling**:
  - StandardScaler for numerical features
  - One-hot encoding for categorical features

**Output**:
- Train/test datasets: `s3://features/prepared_data/{date}/`
- Feature metadata and scaler objects
- Updates Airflow Variable: `latest_prepared_data`

### 3. Model Training Pipeline (`03_model_training_pipeline`)

**Purpose**: Trains multiple models and selects the best performer

**Schedule**: Manual trigger or can be scheduled

**Key Features**:
- **Automatic Retraining Check**:
  - Checks if new data is available since last training
  - Skips if no new data
- **Multiple Model Training**:
  - Baseline: Linear Regression
  - Random Forest (with hyperparameter tuning)
  - Gradient Boosting
- **MLflow Integration**:
  - All runs tracked in single experiment
  - Metrics, parameters, and artifacts logged
  - Best model automatically registered
- **Model Versioning**:
  - Each training creates new version
  - Automatic staging promotion

## 🔄 How Model Retraining Works

### Concept: Continuous Model Improvement

The retraining mechanism ensures your model stays current with new data while maintaining a complete history of all versions.

### Key Components:

1. **Single Experiment, Multiple Runs**
   - All training runs go to: `customer_churn_prediction` experiment
   - Easy comparison of all model versions
   - Track performance over time

2. **Automatic Version Management**
   - Each training creates a new model version
   - Previous versions are preserved
   - Can rollback if needed

3. **Data-Driven Triggers**
   - Training only happens when new data is available
   - Prevents unnecessary retraining
   - Saves compute resources

### Retraining Flow:

```python
1. Check for new data:
   - Compare latest_prepared_data vs last_trained_data
   - If new data exists → proceed
   - If no new data → skip

2. Train multiple models:
   - Each model type trains on new data
   - All runs tracked in MLflow

3. Select best model:
   - Compare all model performances
   - Register best as new version
   - Transition to staging

4. Update metadata:
   - Record training date
   - Save best model info
```

## 🚀 Usage Guide

### Running the Pipelines

#### 1. Start Data Generation (Daily)
```bash
# Trigger manually
airflow dags trigger 01_data_generation_pipeline

# Or let it run on schedule (daily)
```

#### 2. Data Preparation (Auto-triggered)
The preparation pipeline automatically starts after data generation completes.

#### 3. Trigger Model Training
```bash
# Manual trigger
airflow dags trigger 03_model_training_pipeline

# Via Airflow UI
# Go to DAGs → 03_model_training_pipeline → Trigger
```

### Monitoring Training Progress

1. **Airflow UI** (http://localhost:8080):
   - View DAG runs
   - Check task logs
   - Monitor pipeline status

2. **MLflow UI** (http://localhost:5001):
   - View experiments
   - Compare model metrics
   - Inspect model artifacts

3. **MinIO Console** (http://localhost:9001):
   - Browse stored datasets
   - Check model artifacts

## 📈 Model Versioning Example

### First Training (Monday)
```
Data: 1000 records from Sunday
Models trained:
- Linear Regression: RMSE = 0.15
- Random Forest: RMSE = 0.12 ✓ (Best)
- Gradient Boosting: RMSE = 0.13

Result: Random Forest v1 → Staging
```

### Retraining (Tuesday)
```
Data: 2200 records (Sunday + Monday)
Models trained:
- Linear Regression: RMSE = 0.14
- Random Forest: RMSE = 0.11 ✓ (Best)
- Gradient Boosting: RMSE = 0.12

Result: Random Forest v2 → Staging
```

### Benefits:
- Model improves with more data
- Can compare v1 vs v2 performance
- Can rollback to v1 if needed
- Complete audit trail

## 🛠️ Customization

### Adding New Features

Edit `02_data_preparation_pipeline.py`:
```python
def engineer_features(**context):
    # Add your feature here
    df['new_feature'] = df['col1'] * df['col2']
```

### Adding New Models

Edit `03_model_training_pipeline.py`:
```python
def train_xgboost(**context):
    # Your new model training code
    model = XGBRegressor()
    # ... training logic
```

### Changing Retraining Schedule

Edit DAG schedule:
```python
with DAG(
    '03_model_training_pipeline',
    schedule='@weekly',  # Changed from None to weekly
    ...
)
```

## 📊 Best Practices

1. **Data Quality**
   - Monitor data quality scores
   - Investigate sudden distribution changes
   - Set alerts for quality degradation

2. **Model Monitoring**
   - Track performance metrics over time
   - Watch for model drift
   - Compare new vs old versions

3. **Resource Management**
   - Use Airflow pools for training tasks
   - Limit concurrent model training
   - Clean up old artifacts periodically

4. **Experiment Tracking**
   - Use descriptive run names
   - Log all hyperparameters
   - Document model changes

## 🔍 Troubleshooting

### Pipeline Failures

1. **Data Generation Fails**
   ```bash
   # Check logs
   airflow dags test 01_data_generation_pipeline <date>
   
   # Verify S3 access
   docker exec -it <scheduler-container> python
   >>> import boto3
   >>> s3 = boto3.client('s3', endpoint_url='http://minio:9000', ...)
   ```

2. **Model Training Skips**
   ```bash
   # Check Variables
   airflow variables get latest_prepared_data
   airflow variables get last_trained_data
   
   # Force training
   airflow variables delete last_trained_data
   ```

3. **MLflow Connection Issues**
   ```bash
   # Test MLflow
   curl http://localhost:5001/api/2.0/experiments/list
   
   # Check logs
   docker logs mlops_e52901-mlflow-1
   ```

## 📋 Monitoring Checklist

Daily:
- [ ] Data generation successful
- [ ] Data quality score > 90%
- [ ] Preparation pipeline completed

Weekly:
- [ ] Model retrained with new data
- [ ] Performance metrics improved or stable
- [ ] No data drift detected

Monthly:
- [ ] Review all model versions
- [ ] Clean up old artifacts
- [ ] Update feature engineering if needed

## 🎯 Advanced Topics

### A/B Testing Models
1. Keep multiple versions in staging
2. Route traffic between versions
3. Compare real-world performance

### Automated Promotion
```python
# Add to select_best_model()
if test_rmse < 0.10:  # Threshold
    client.transition_model_version_stage(
        name=MODEL_NAME,
        version=model_version.version,
        stage="Production"
    )
```

### Feature Store Integration
- Use Feast for feature serving
- Ensure training/serving consistency
- Version features with models

## 📚 Additional Resources

- [MLflow Model Registry](https://mlflow.org/docs/latest/model-registry.html)
- [Airflow Best Practices](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html)
- [Feature Engineering Guide](https://feast.dev/docs/getting-started/concepts/feature-retrieval/)

---

**Remember**: The key to successful model retraining is maintaining a balance between staying current with new data and avoiding unnecessary compute costs. This pipeline achieves that through intelligent checking and automated versioning. 