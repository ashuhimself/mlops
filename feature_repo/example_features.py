from datetime import timedelta
from feast import Entity, Feature, FeatureView, FileSource, ValueType
from feast.types import Float32, Int64, String

# Define an entity for user features
user = Entity(
    name="user_id",
    value_type=ValueType.INT64,
    description="User ID"
)

# Define a file source for user features
user_stats_source = FileSource(
    path="/data/user_stats.parquet",  # This would be your actual data path
    timestamp_field="event_timestamp",
)

# Define a feature view
user_stats_fv = FeatureView(
    name="user_stats",
    entities=["user_id"],
    ttl=timedelta(days=1),
    schema=[
        Feature(name="total_purchases", dtype=Int64),
        Feature(name="avg_purchase_value", dtype=Float32),
        Feature(name="days_since_last_purchase", dtype=Int64),
    ],
    source=user_stats_source,
    online=True,
    tags={"team": "ml", "status": "production"},
) 