
import os, json, boto3, datetime, uuid

dynamodb = boto3.resource('dynamodb')
faq_table = dynamodb.Table(os.environ['FAQ_TABLE_NAME'])
log_table = dynamodb.Table(os.environ['LOG_TABLE_NAME'])
ses = boto3.client('ses')

def find_answer_from_faq(user_text: str):
    # naive keyword match over q_keywords list in items
    # For demo: scan is OK. Production would use Kendra/OpenSearch.
    user_text_l = (user_text or '').casefold()
    resp = faq_table.scan(ProjectionExpression='id, answer, q_keywords')
    for item in resp.get('Items', []):
        for kw in item.get('q_keywords', []):
            if kw.casefold() in user_text_l:
                return item['answer']
    return None

def log_interaction(user_text: str, answer: str|None, confidence: float|None, session_id: str|None, intent_name: str|None):
    log_table.put_item(Item={
        'id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'query': user_text,
        'answer': (answer[:500] if answer else None),
        'confidence': float(confidence) if confidence is not None else None,
        'intent': intent_name,
        'sessionId': session_id
    })

def send_escalation_email(user_text: str):
    ses.send_email(
        Source=os.environ['SOURCE_EMAIL'],
        Destination={'ToAddresses': [os.environ['SUPPORT_EMAIL']]},
        Message={
            'Subject': {'Data': 'AssistIQ escalation: user needs help'},
            'Body': {'Text': {'Data': f'AssistIQ could not answer this query:\n\n{user_text}'}}
        }
    )

def _build_response(message: str):
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": "ProvideSupport", "state": "Fulfilled"}
        },
        "messages": [{"contentType": "PlainText", "content": message}]
    }

def lambda_handler(event, context):
    # Lex V2 fulfillment event
    user_text = event.get('inputTranscript') or event.get('inputText') or ''
    session_id = (event.get('sessionId') or event.get('sessionId', '')) if isinstance(event, dict) else None
    # nlu confidence if provided
    conf = None
    intent_name = None
    try:
        interpretations = event.get('interpretations') or []
        if interpretations:
            conf = (interpretations[0].get('nluConfidence') or {}).get('score')
            intent_name = (interpretations[0].get('intent') or {}).get('name')
    except Exception:
        pass

    answer = find_answer_from_faq(user_text)
    if answer:
        log_interaction(user_text, answer, conf, session_id, intent_name)
        return _build_response(answer)

    # No answer -> escalate
    try:
        send_escalation_email(user_text)
        fallback = "I couldn't find an answer. I've forwarded your query to our IT team—someone will reach out soon."
    except Exception as e:
        fallback = "I couldn't find an answer and failed to escalate via email. Please contact IT support directly."
    log_interaction(user_text, None, conf, session_id, intent_name)
    return _build_response(fallback)
