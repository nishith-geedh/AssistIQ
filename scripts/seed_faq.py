
#!/usr/bin/env python3
import boto3, json, sys, os
table_name = os.environ.get("FAQ_TABLE") or sys.argv[1] if len(sys.argv)>1 else None
if not table_name:
  print("Usage: FAQ_TABLE=<name> python3 scripts/seed_faq.py or python3 scripts/seed_faq.py <table>"); exit(1)
ddb = boto3.resource('dynamodb')
t = ddb.Table(table_name)
items = json.load(open('scripts/seed_faq.json'))
for it in items:
  t.put_item(Item=it)
print(f"Seeded {len(items)} items into {table_name}")
