#!/usr/bin/env python3
"""
Seed intents into a DynamoDB table.

Usage:
  # Option 1: pass table name
  python3 scripts/seed_intents.py AssistIQ-IT_FAQ

  # Option 2: set env var and run
  TABLE=AssistIQ-IT_FAQ python3 scripts/seed_intents.py
"""
import sys, os, json, boto3
from botocore.exceptions import ClientError

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    table_name = os.environ.get("TABLE") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not table_name:
        print("Usage: python3 scripts/seed_intents.py <DynamoDBTableName>")
        sys.exit(1)

    path = os.path.join(os.path.dirname(__file__), "intents.json")
    if not os.path.exists(path):
        print("Cannot find scripts/intents.json. Save the intents JSON at scripts/intents.json")
        sys.exit(1)

    items = load_json(path)
    ddb = boto3.resource('dynamodb')
    table = ddb.Table(table_name)

    for it in items:
        # ensure id exists
        if not it.get("id"):
            print("Skipping item without id:", it)
            continue
        # convert python lists/dicts into DynamoDB-friendly types via boto3 resource
        try:
            table.put_item(Item=it)
            print("Inserted/Updated:", it["id"])
        except ClientError as e:
            print("Failed to put item", it["id"], e)

if __name__ == "__main__":
    main()
