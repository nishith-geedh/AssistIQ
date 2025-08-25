import os
import json
import boto3
import uuid

lex = boto3.client('lexv2-runtime')

BOT_ID = os.environ.get('BOT_ID')
BOT_ALIAS_ID = os.environ.get('BOT_ALIAS_ID')
BOT_LOCALE_ID = os.environ.get('BOT_LOCALE_ID', 'en_US')

def lambda_handler(event, context):
    # Parse incoming HTTP API event body safely
    try:
        body = json.loads(event.get('body') or '{}')
    except Exception:
        body = {}

    text = (body.get('text') or '').strip()
    session_id = body.get('sessionId') or str(uuid.uuid4())

    # Validate required environment variables
    if not BOT_ID or not BOT_ALIAS_ID:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "error": "Lex bot not configured (BOT_ID or BOT_ALIAS_ID missing)."
            })
        }

    # Validate input text
    if not text:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "error": "Missing required parameter: text"
            })
        }

    try:
        resp = lex.recognize_text(
            botId=BOT_ID,
            botAliasId=BOT_ALIAS_ID,
            localeId=BOT_LOCALE_ID,
            sessionId=session_id,
            text=text
        )
    except Exception as e:
        # Log the error, then return a 500 response
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "error": "Error calling Lex recognize_text",
                "details": str(e)
            })
        }

    messages = resp.get('messages') or []
    answer = "\n".join(m.get('content', '') for m in messages)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps({
            "sessionId": session_id,
            "messages": messages,
            "raw": resp,
            "answer": answer
        })
    }
