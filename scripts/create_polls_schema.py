import os
import boto3


def main():
    endpoint_url = os.getenv("DYNAMODB_URL", "http://127.0.0.1:8000")
    region = os.getenv("AWS_REGION", "us-east-1")
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "dummy")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy")
    table_name = os.getenv("DYNAMODB_POLLS_TABLE", "Polls")

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

    existing = [t.name for t in dynamodb.tables.all()]
    if table_name in existing:
        print(f"Table {table_name} already exists")
        return

    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    print(f"Created table {table_name}")


if __name__ == "__main__":
    main()

