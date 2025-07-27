#!/usr/bin/env python3
"""Test S3 (MinIO) Connection from Jupyter"""

import boto3
import pandas as pd
import os
from datetime import datetime

print("=" * 50)
print("Testing S3 (MinIO) Connection from Jupyter")
print("=" * 50)

# Display configuration
print("\n1. Environment Configuration:")
print(f"   AWS_ACCESS_KEY_ID: {os.environ.get('AWS_ACCESS_KEY_ID', 'Not set')}")
print(f"   AWS_SECRET_ACCESS_KEY: {'***' if os.environ.get('AWS_SECRET_ACCESS_KEY') else 'Not set'}")
print(f"   AWS_ENDPOINT_URL: {os.environ.get('AWS_ENDPOINT_URL', 'Not set')}")
print(f"   MLFLOW_TRACKING_URI: {os.environ.get('MLFLOW_TRACKING_URI', 'Not set')}")

# Create S3 client
print("\n2. Creating S3 client...")
try:
    s3_client = boto3.client(
        's3',
        endpoint_url=os.environ.get('AWS_ENDPOINT_URL', 'http://minio:9000'),
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID', 'minio'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY', 'minio123')
    )
    print("   ✅ S3 client created successfully!")
except Exception as e:
    print(f"   ❌ Error creating S3 client: {e}")
    exit(1)

# List buckets
print("\n3. Listing buckets...")
try:
    buckets = s3_client.list_buckets()
    print("   Available buckets:")
    for bucket in buckets['Buckets']:
        print(f"     - {bucket['Name']}")
except Exception as e:
    print(f"   ❌ Error listing buckets: {e}")
    exit(1)

# Create test data
print("\n4. Creating test data...")
test_data = pd.DataFrame({
    'timestamp': pd.date_range(start='2024-01-01', periods=5, freq='H'),
    'value': range(5),
    'category': ['A', 'B', 'A', 'B', 'A']
})
print("   Test data created:")
print(test_data.to_string(index=False))

# Save to S3
print("\n5. Saving data to S3...")
try:
    csv_buffer = test_data.to_csv(index=False)
    key = f"jupyter_test/test_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    s3_client.put_object(
        Bucket='features',
        Key=key,
        Body=csv_buffer
    )
    print(f"   ✅ Data saved to s3://features/{key}")
except Exception as e:
    print(f"   ❌ Error saving to S3: {e}")
    exit(1)

# Read from S3
print("\n6. Reading data from S3...")
try:
    response = s3_client.get_object(Bucket='features', Key=key)
    df_from_s3 = pd.read_csv(response['Body'])
    print("   ✅ Data read successfully!")
    print("   First 3 rows:")
    print(df_from_s3.head(3).to_string(index=False))
except Exception as e:
    print(f"   ❌ Error reading from S3: {e}")
    exit(1)

# List objects
print("\n7. Listing objects in bucket...")
try:
    objects = s3_client.list_objects_v2(Bucket='features', Prefix='jupyter_test/')
    if 'Contents' in objects:
        print("   Objects in s3://features/jupyter_test/:")
        for obj in objects['Contents'][-5:]:  # Show last 5 objects
            print(f"     - {obj['Key']} (Size: {obj['Size']} bytes)")
    else:
        print("   No objects found")
except Exception as e:
    print(f"   ❌ Error listing objects: {e}")

print("\n" + "=" * 50)
print("✅ All S3 connection tests passed!")
print("=" * 50) 