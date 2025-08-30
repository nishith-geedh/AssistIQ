import os
import json
import uuid
import time
import boto3
from boto3.dynamodb.conditions import Attr

lex_client = boto3.client("lexv2-runtime")
dynamodb = boto3.resource("dynamodb")

BOT_ID = os.environ.get("BOT_ID")
BOT_ALIAS_ID = os.environ.get("BOT_ALIAS_ID")
BOT_LOCALE_ID = os.environ.get("BOT_LOCALE_ID", "en_US")
LOGS_TABLE_NAME = os.environ.get("LOGS_TABLE_NAME", "AssistIQ-ChatLogs")

log_table = dynamodb.Table(LOGS_TABLE_NAME)

def _cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "OPTIONS,GET,POST",
        "Access-Control-Allow-Headers": "*",
    }

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps(body),
    }

def _scan_history(session_id):
    items = []
    try:
        resp = log_table.scan(FilterExpression=Attr("session_id").eq(session_id))
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = log_table.scan(
                FilterExpression=Attr("session_id").eq(session_id),
                ExclusiveStartKey=resp["LastEvaluatedKey"]
            )
            items.extend(resp.get("Items", []))
    except Exception as e:
        print(f"[WARN] history scan failed for {session_id}: {e}")
    items.sort(key=lambda x: x.get("timestamp", ""))
    return items

def _log(session_id, user_text, bot_reply):
    try:
        log_table.put_item(
            Item={
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "user_text": user_text,
                "bot_reply": bot_reply
            }
        )
    except Exception as e:
        print(f"[ERROR] log put_item failed: {e}")

def lambda_handler(event, context):
    # Handle CORS preflight (OPTIONS)
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _response(204, {})

    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        body = {}

    user_text = (body.get("text") or "").strip()
    session_id = body.get("sessionId") or str(uuid.uuid4())

    if not BOT_ID or not BOT_ALIAS_ID:
        return _response(500, {"error": "Lex bot not configured."})
    if not user_text:
        return _response(400, {"error": "Missing required parameter: text"})

    try:
        lex_resp = lex_client.recognize_text(
            botId=BOT_ID,
            botAliasId=BOT_ALIAS_ID,
            localeId=BOT_LOCALE_ID,
            sessionId=session_id,
            text=user_text,
        )
    except Exception as e:
        return _response(500, {"error": "Error calling Lex", "details": str(e)})

    # Compose bot reply
    msg_chunks = [m.get("content", "") for m in lex_resp.get("messages", []) if m.get("content")]
    bot_reply = "\n".join(msg_chunks) if msg_chunks else ""

    # Save to logs
    _log(session_id, user_text, bot_reply)

    # Build history array
    history_items = _scan_history(session_id)
    messages = []
    for itm in history_items:
        if "user_text" in itm:
            messages.append({"role": "user", "content": itm["user_text"], "timestamp": itm.get("timestamp")})
        if "bot_reply" in itm:
            messages.append({"role": "bot", "content": itm["bot_reply"], "timestamp": itm.get("timestamp")})

    # Include 'answer' explicitly for the frontend
    return _response(200, {
        "sessionId": session_id,
        "answer": bot_reply or None,
        "messages": messages,
        "rawLex": lex_resp
    })
