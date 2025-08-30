import os
import boto3
import uuid
from decimal import Decimal
from datetime import datetime

# --- DynamoDB + SES Clients ---
dynamodb = boto3.resource("dynamodb")
chatlog_table = dynamodb.Table(os.environ["LOGS_TABLE_NAME"])
intent_table = dynamodb.Table(os.environ["FAQ_TABLE_NAME"])
session_table = dynamodb.Table(os.environ["SESSION_TABLE_NAME"])
ses_client = boto3.client("ses", region_name="us-east-1")

SOURCE_EMAIL = os.environ["SOURCE_EMAIL"]
SUPPORT_EMAIL = os.environ["SUPPORT_EMAIL"]

# ================== Utilities ==================

def _safe_str(val):
    return val if val else ""

def log_interaction(user_text, intent_name, confidence, session_id, bot_reply):
    """Save conversation turns to DynamoDB."""
    try:
        chatlog_table.put_item(Item={
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "user_text": user_text,
            "intent_name": intent_name,
            "confidence": Decimal(str(confidence)),
            "bot_reply": bot_reply
        })
    except Exception as e:
        print("log_interaction error:", e)

def get_intent_from_db(intent_name):
    try:
        return intent_table.get_item(Key={"id": intent_name}).get("Item")
    except Exception as e:
        print("get_intent_from_db error:", e)
        return None

def get_session_state(session_id):
    try:
        return session_table.get_item(Key={"id": session_id}).get("Item", {})
    except Exception as e:
        print("get_session_state error:", e)
        return {}

def set_session_state(session_id, state):
    try:
        session_table.put_item(Item={"id": session_id, **state})
    except Exception as e:
        print("set_session_state error:", e)

def clear_session_state(session_id):
    try:
        session_table.delete_item(Key={"id": session_id})
    except Exception as e:
        print("clear_session_state error:", e)

# ================== Email Helpers ==================

def fetch_conversation(session_id):
    """Retrieve and sort full conversation history for a session."""
    try:
        resp = chatlog_table.scan()
        convo = [item for item in resp.get("Items", []) if item.get("session_id") == session_id]
        return sorted(convo, key=lambda x: x.get("timestamp", ""))
    except Exception as e:
        print("fetch_conversation error:", e)
        return []

def send_escalation_email(full_conversation, session_id, issue_type="General Issue"):
    """Send full transcript to IT via SES."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"AssistIQ Escalation: {issue_type} (Session {session_id})"

    excluded = {"GreetingIntent", "ThanksIntent"}
    convo_text = "\n".join(
        f"[{c.get('timestamp')}] User: {_safe_str(c.get('user_text'))} | Bot: {_safe_str(c.get('bot_reply'))}"
        for c in full_conversation if c.get("intent_name") not in excluded
    )

    body = (
        f"⚠️ AssistIQ Escalation Notification\n\n"
        f"Session ID: {session_id}\n"
        f"Timestamp: {timestamp}\n"
        f"Issue Type: {issue_type}\n\n"
        f"Conversation Transcript:\n{convo_text}\n\n"
        "Please review and take appropriate action."
    )

    try:
        resp = ses_client.send_email(
            Source=SOURCE_EMAIL,
            Destination={"ToAddresses": [SUPPORT_EMAIL]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}}
            }
        )
        return resp.get("MessageId") is not None
    except Exception as e:
        print("SES escalation send error:", e)
        return False

# ================== Lex Response Builders ==================

def build_response(message, intent_name="FallbackIntent", session_state=None):
    return {
        "sessionState": session_state or {
            "dialogAction": {"type": "Close"},
            "intent": {"name": intent_name, "state": "Fulfilled"}
        },
        "messages": [{"contentType": "PlainText", "content": _safe_str(message)}],
    }

def elicit_slot_response(slot_to_elicit, message, intent_name, slots):
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": slot_to_elicit},
            "intent": {"name": intent_name, "slots": slots, "state": "InProgress"}
        },
        "messages": [{"contentType": "PlainText", "content": _safe_str(message)}],
    }

# ================== Fulfillment Helper ==================

def fulfill_intent_from_db(user_text, intent_name, session_id):
    intent_item = get_intent_from_db(intent_name)
    if intent_item:
        reply = f"{_safe_str(intent_item.get('fulfillment'))}\n\n{_safe_str(intent_item.get('closing_response'))}".strip()
    else:
        reply = "I have processed your request."

    # ✅ Log first before escalation
    log_interaction(user_text, intent_name, 1.0, session_id, reply)

    excluded_from_escalation = {"GreetingIntent", "ThanksIntent"}
    if intent_name not in excluded_from_escalation:
        convo = fetch_conversation(session_id)
        send_escalation_email(convo, session_id, issue_type=intent_name)

    clear_session_state(session_id)
    return build_response(reply, intent_name)

# ================== Lambda Handler ==================

def lambda_handler(event, context):
    print("Fulfillment Lambda event keys:", list(event.keys()))

    user_text = (event.get("inputTranscript") or event.get("inputText") or "").strip()
    session_id = event.get("sessionId") or str(uuid.uuid4())
    print("Resolved session_id:", session_id, "user_text:", user_text)

    session_state = get_session_state(session_id)

    intent_state = event.get("sessionState", {}) or {}
    intent = intent_state.get("intent", {}) or {}
    intent_name = intent.get("name")
    slots = intent.get("slots", {}) or {}

    # --- Handle confirmation state ---
    confirmation_state = intent.get("confirmationState")
    if confirmation_state == "Denied":
        reply = "Okay — I have cancelled that request. Let me know if you need anything else."
        log_interaction(user_text, intent_name or "UnknownIntent", 1.0, session_id, reply)
        clear_session_state(session_id)
        return build_response(reply, intent_name or "FallbackIntent")

    if confirmation_state == "Confirmed":
        return fulfill_intent_from_db(user_text, intent_name, session_id)

    # --- Handle confirm slot ---
    confirm_slot = slots.get("confirm")
    if confirm_slot and confirm_slot.get("value"):
        interpreted = confirm_slot["value"].get("interpretedValue", "").strip().lower()
        positives = {"yes", "yeah", "yep", "sure", "ok", "okay"}
        negatives = {"no", "nah", "nope", "cancel", "stop"}

        if interpreted in positives:
            return fulfill_intent_from_db(user_text, intent_name, session_id)
        if interpreted in negatives:
            reply = "Okay — I have cancelled that request. Let me know if you need anything else."
            log_interaction(user_text, intent_name or "UnknownIntent", 1.0, session_id, reply)
            clear_session_state(session_id)
            return build_response(reply, intent_name or "FallbackIntent")

        return elicit_slot_response("confirm", "Please reply with yes or no.", intent_name, slots)

    # --- Greeting intent ---
    if user_text.lower() in {"hi", "hello", "hey"}:
        intent_item = get_intent_from_db("GreetingIntent")
        reply = _safe_str(intent_item.get("fulfillment")) or _safe_str(intent_item.get("initial_response")) or "Hello!"
        log_interaction(user_text, "GreetingIntent", 1.0, session_id, reply)
        return build_response(reply, "GreetingIntent")

    # --- Thanks intent ---
    if user_text.lower() in {"thanks", "thank you", "thx"}:
        intent_item = get_intent_from_db("ThanksIntent")
        reply = _safe_str(intent_item.get("fulfillment")) or _safe_str(intent_item.get("initial_response")) or "You're welcome!"
        log_interaction(user_text, "ThanksIntent", 1.0, session_id, reply)
        return build_response(reply, "ThanksIntent")

    # --- Handle awaiting confirmation session state ---
    if session_state.get("awaiting_confirmation") and session_state.get("intent_id"):
        positives = {"yes", "yeah", "yep", "sure", "ok", "okay"}
        negatives = {"no", "nah", "nope", "cancel", "stop"}

        if user_text.lower() in positives:
            return fulfill_intent_from_db(user_text, session_state["intent_id"], session_id)
        if user_text.lower() in negatives:
            reply = "Okay — I have cancelled that request. Let me know if you need anything else."
            log_interaction(user_text, session_state.get("intent_id"), 1.0, session_id, reply)
            clear_session_state(session_id)
            return build_response(reply, session_state.get("intent_id"))

        return build_response(session_state.get("confirmation_prompt") or "Please reply with yes or no.", "FallbackIntent")

    # --- Handle known intents ---
    if intent_name:
        intent_item = get_intent_from_db(intent_name)
        if intent_item:
            if intent_item.get("confirmation"):
                set_session_state(session_id, {
                    "awaiting_confirmation": True,
                    "intent_id": intent_item["id"],
                    "confirmation_prompt": intent_item["confirmation"]
                })
                reply = _safe_str(intent_item["confirmation"])
                log_interaction(user_text, intent_item["id"], 1.0, session_id, reply)
                return build_response(reply, intent_item["id"])

            return fulfill_intent_from_db(user_text, intent_item["id"], session_id)

    # --- Fallback escalation ---
    fallback = get_intent_from_db("FallbackIntent")
    fallback_msg = _safe_str(fallback.get("initial_response")) if fallback else "I couldn’t understand that. Escalating to IT."

    # ✅ Log first, then escalate
    log_interaction(user_text, "FallbackIntent", 0.0, session_id, fallback_msg)

    convo = fetch_conversation(session_id)
    escalated = send_escalation_email(convo, session_id, issue_type="FallbackIntent")

    if escalated:
        fallback_msg += " Your request has been forwarded to IT."
    else:
        fallback_msg += " (Escalation failed, please contact IT directly.)"

    clear_session_state(session_id)
    return build_response(fallback_msg, "FallbackIntent")
