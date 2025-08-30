import os
import boto3
import uuid
from decimal import Decimal
from datetime import datetime

# --- DynamoDB and SES Clients ---
dynamodb = boto3.resource("dynamodb")
chatlog_table = dynamodb.Table(os.environ["LOGS_TABLE_NAME"])
intent_table = dynamodb.Table(os.environ["FAQ_TABLE_NAME"])
session_table = dynamodb.Table(os.environ["SESSION_TABLE_NAME"])
ses_client = boto3.client("ses", region_name="ap-south-1")

SOURCE_EMAIL = os.environ["SOURCE_EMAIL"]
SUPPORT_EMAIL = os.environ["SUPPORT_EMAIL"]

# --- Utilities ---
def log_interaction(user_text, intent_name, confidence, session_id, bot_reply):
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

def send_escalation_email(user_text, session_id):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"AssistIQ Escalation: Session {session_id}"
    body = (
        f"⚠️ AssistIQ Escalation Notification\n\n"
        f"Session ID: {session_id}\n"
        f"Timestamp: {timestamp}\n\n"
        f"User input that could not be handled automatically:\n\"{user_text}\"\n\n"
        "Please review and take appropriate action."
    )
    try:
        resp = ses_client.send_email(
            Source=SOURCE_EMAIL,
            Destination={"ToAddresses": [SUPPORT_EMAIL]},
            Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}}
        )
        return resp.get("MessageId") is not None
    except Exception as e:
        print("SES send error:", e)
        return False

# --- Lex response builders ---
def build_response(message, intent_name="FallbackIntent", session_state=None):
    return {
        "sessionState": session_state or {
            "dialogAction": {"type": "Close"},
            "intent": {"name": intent_name, "state": "Fulfilled"}
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }

def elicit_slot_response(slot_to_elicit, message, intent_name, slots):
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": slot_to_elicit},
            "intent": {"name": intent_name, "slots": slots, "state": "InProgress"}
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }

def delegate_response(intent_name, slots):
    return {
        "sessionState": {
            "dialogAction": {"type": "Delegate"},
            "intent": {"name": intent_name, "slots": slots, "state": "InProgress"}
        }
    }

# --- Core helper: finalize/fulfill an intent (keeps earlier behaviour) ---
def fulfill_intent_from_db(user_text, intent_name, session_id):
    intent_item = get_intent_from_db(intent_name)
    if intent_item:
        reply = f"{intent_item.get('fulfillment', '')}\n\n{intent_item.get('closing_response', '')}".strip()
    else:
        reply = "I have processed your request."
    log_interaction(user_text, intent_name or "UnknownIntent", 1.0, session_id, reply)
    clear_session_state(session_id)
    # return the same intent name (Lex requires the name to exist)
    return build_response(reply, intent_name or "FallbackIntent")

# --- Main Lambda handler ---
def lambda_handler(event, context):
    # Debug info for CloudWatch
    print("Fulfillment Lambda event keys:", list(event.keys()))

    user_text = (event.get("inputTranscript") or event.get("inputText") or "").strip()
    session_id = event.get("sessionId") or str(uuid.uuid4())
    print("resolved session_id:", session_id, "user_text:", user_text)

    session_state = get_session_state(session_id)

    intent_state = event.get("sessionState", {}) or {}
    intent = intent_state.get("intent", {}) or {}
    intent_name = intent.get("name")
    slots = intent.get("slots", {}) or {}

    # -------------- Handle Lex confirmationState first (global) --------------
    confirmation_state = intent.get("confirmationState")  # None | Confirmed | Denied
    if confirmation_state:
        print("confirmationState:", confirmation_state, "for intent:", intent_name)
        if confirmation_state == "Denied":
            reply = "Okay — I have cancelled that request. Let me know if you need anything else."
            log_interaction(user_text, intent_name or "UnknownIntent", 1.0, session_id, reply)
            clear_session_state(session_id)
            # Return Close with the same intent name (must exist) or fallback
            return build_response(reply, intent_name or "FallbackIntent")
        elif confirmation_state == "Confirmed":
            # proceed to fulfillment via DB entry
            return fulfill_intent_from_db(user_text, intent_name, session_id)

    # -------------- Handle confirm slot generically (if present) --------------
    confirm_slot = slots.get("confirm")
    if confirm_slot and confirm_slot.get("value"):
        interpreted = confirm_slot["value"].get("interpretedValue", "").strip().lower()
        print("confirm slot interpreted:", interpreted)
        positives = {"yes", "yeah", "yep", "sure", "ok", "okay"}
        negatives = {"no", "nah", "nope", "cancel", "stop"}

        if interpreted in positives:
            return fulfill_intent_from_db(user_text, intent_name, session_id)
        if interpreted in negatives:
            reply = "Okay — I have cancelled that request. Let me know if you need anything else."
            log_interaction(user_text, intent_name or "UnknownIntent", 1.0, session_id, reply)
            clear_session_state(session_id)
            return build_response(reply, intent_name or "FallbackIntent")
        # if unclear:
        prompt = "Please reply with yes or no."
        log_interaction(user_text, intent_name or "UnknownIntent", 0.0, session_id, prompt)
        return elicit_slot_response("confirm", prompt, intent_name, slots)

    # -------------- No text provided --------------
    if not user_text:
        reply = "Sorry, I didn't get that. Could you please say that again?"
        log_interaction(user_text, "FallbackIntent", 0.0, session_id, reply)
        return build_response(reply, "FallbackIntent")

    normalized = user_text.lower()

    # -------------- Small talk overrides --------------
    if normalized in {"hi", "hello", "hey"}:
        intent_item = get_intent_from_db("GreetingIntent")
        reply = intent_item.get("fulfillment") or intent_item.get("initial_response", "Hello!") if intent_item else "Hello!"
        log_interaction(user_text, "GreetingIntent", 1.0, session_id, reply)
        return build_response(reply, "GreetingIntent")

    if normalized in {"thanks", "thank you", "thx"}:
        intent_item = get_intent_from_db("ThanksIntent")
        reply = intent_item.get("fulfillment") or intent_item.get("initial_response", "You're welcome!") if intent_item else "You're welcome!"
        log_interaction(user_text, "ThanksIntent", 1.0, session_id, reply)
        return build_response(reply, "ThanksIntent")

    # -------------- Legacy session-based confirmation (kept for compatibility) --------------
    if session_state.get("awaiting_confirmation") and session_state.get("intent_id"):
        positives = {"yes", "yeah", "yep", "sure", "ok", "okay"}
        negatives = {"no", "nah", "nope", "cancel", "stop"}

        if normalized in positives:
            intent_id = session_state["intent_id"]
            intent_item = get_intent_from_db(intent_id)
            reply = f"{intent_item.get('fulfillment', '')}\n\n{intent_item.get('closing_response', '')}".strip() if intent_item else "Confirmed."
            log_interaction(user_text, intent_id, 1.0, session_id, reply)
            clear_session_state(session_id)
            return build_response(reply, intent_id)

        if normalized in negatives:
            reply = "Okay — I have cancelled that request. Let me know if you need anything else."
            # map to the original intent id
            intent_id = session_state.get("intent_id") or intent_name or "FallbackIntent"
            log_interaction(user_text, intent_id, 1.0, session_id, reply)
            clear_session_state(session_id)
            return build_response(reply, intent_id)

        prompt = session_state.get("confirmation_prompt") or "Please reply with yes or no."
        log_interaction(user_text, "FallbackIntent", 0.0, session_id, prompt)
        return build_response(prompt, "FallbackIntent")

    # -------------- Intent fulfillment by DB lookup --------------
    if intent_name:
        intent_item = get_intent_from_db(intent_name)
        if intent_item:
            # If the intent requires confirmation, keep the legacy confirmation flow
            if intent_item.get("confirmation"):
                set_session_state(session_id, {
                    "awaiting_confirmation": True,
                    "intent_id": intent_item["id"],
                    "confirmation_prompt": intent_item["confirmation"]
                })
                reply = intent_item["confirmation"]
                log_interaction(user_text, intent_item["id"], 1.0, session_id, reply)
                return build_response(reply, intent_item["id"])
            # otherwise fulfill now
            reply = f"{intent_item.get('fulfillment', '')}\n\n{intent_item.get('closing_response', '')}".strip()
            log_interaction(user_text, intent_item["id"], 1.0, session_id, reply)
            clear_session_state(session_id)
            return build_response(reply, intent_item["id"])

    # -------------- Fallback --------------
    fallback = get_intent_from_db("FallbackIntent")
    fallback_msg = fallback.get("initial_response") if fallback else "I couldn’t understand that. Escalating to IT."
    escalated = send_escalation_email(user_text, session_id)
    fallback_msg += " Your request has been forwarded to IT." if escalated else " (Escalation failed, please contact IT directly.)"
    log_interaction(user_text, "FallbackIntent", 0.0, session_id, fallback_msg)
    clear_session_state(session_id)
    return build_response(fallback_msg, "FallbackIntent")
