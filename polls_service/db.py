import os
from functools import lru_cache
from typing import Tuple
import boto3
from botocore.config import Config


@lru_cache(maxsize=1)
def get_dynamodb_resource():
    """
    Directive: returns a cached DynamoDB resource connected to DynamoDB Local or AWS.
    Configure with:
      - DYNAMODB_URL (e.g., http://127.0.0.1:8000 for local)
      - AWS_REGION (default: us-east-1)
      - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (dummy for local)
    """
    endpoint_url = os.getenv("DYNAMODB_URL")
    region = os.getenv("AWS_REGION", "us-east-1")
    # For DynamoDB Local, dummy credentials are required by the SDK
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "dummy")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy")
    session = boto3.session.Session()
    return session.resource(
        "dynamodb",
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )


def get_polls_table():
    """
    Dependency: retrieve the polls table object (single-table design).
    Table schema:
      - pk (HASH)
      - sk (RANGE)
    Denormalized items:
      - Poll item:    pk= P#{poll_id}, sk= POLL, attrs: question, options(list[str]), count0..count3, created_by, created_at
      - Vote item:    pk= P#{poll_id}, sk= V#{username}, attrs: choice_index
    """
    dynamodb = get_dynamodb_resource()
    table_name = os.getenv("DYNAMODB_POLLS_TABLE", "Polls")
    return dynamodb.Table(table_name)


