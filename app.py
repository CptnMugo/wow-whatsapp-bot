from flask import Flask, request
import requests
import os
import re
from datetime import datetime

app = Flask(__name__)

WA_TOKEN = os.getenv("WA_TOKEN")
PHONE_ID = os.getenv("PHONE_ID")
SHEETS_URL = os.getenv("SHEETS_URL")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# Simple in-memory state. Use Redis/DB for production
user_states = {}

def send_wa_message(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WA_TOKEN}"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=data)

@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Invalid", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    try:
        value = data['entry'][0]['changes'][0]['value']
        if 'messages' not in value:
            return "OK", 200

        msg = value['messages'][0]
        user_phone = msg['from']

        # For Phase 1: only accept text. Voice comes in Phase 2
        if msg['type']!= 'text':
            send_wa_message(user_phone, "Please send text replies for now. Voice support coming soon.")
            return "OK", 200

        msg_text = msg['text']['body'].strip()
    except:
        return "OK", 200

    state = user_states.get(user_phone, {"step": "consent", "data": {}})

    # CONSENT STEP
    if state["step"] == "consent":
        send_wa_message(user_phone,
            "Thank you for contacting WOW Business Assistant.\n\n"
            "Please save this number as WOW Assistant.\n\n"
            "Before we continue, please reply YES to consent to us collecting your information "
            "so we can understand your business needs and contact you about the WOW tool."
        )
        state["step"] = "await_consent"

    elif state["step"] == "await_consent":
        if re.match(r'^y(es)?$', msg_text, re.I):
            state["step"] = "q1"
            send_wa_message(user_phone, "What is your full name?")
        elif re.match(r'^n(o)?$', msg_text, re.I):
            send_wa_message(user_phone,
                "Understood. We won't collect your data. Type YES anytime to restart."
            )
            state = {"step": "consent", "data": {}} # Reset + terminate
        else:
            send_wa_message(user_phone, "Please reply YES to continue, or NO to cancel.")

    # Q1: Full Name
    elif state["step"] == "q1":
        state["data"]["full_name"] = msg_text
        state["step"] = "q2"
        send_wa_message(user_phone,
            "Are you interested in?\n"
            "1 = Proof of Concept\n"
            "2 = Pilot\n"
            "3 = More Information\n"
            "4 = All of the above"
        )

    # Q2: Interest Type - with validation + rules
    elif state["step"] == "q2":
        valid_options = {"1": "Proof of Concept", "2": "Pilot", "3": "More Information", "4": "All of the above"}
        if msg_text in valid_options:
            state["data"]["interest_type"] = valid_options[msg_text]
            if msg_text == "3":
                state["data"]["tag"] = "info_only" # Rule: tag if option 3
            state["step"] = "q3"
            send_wa_message(user_phone, "Type of business?")
        else:
            send_wa_message(user_phone, "Please reply 1, 2, 3, or 4")

    # Q3: Business Type
    elif state["step"] == "q3":
        state["data"]["business_type"] = msg_text
        state["step"] = "q4"
        send_wa_message(user_phone, "Record-keeping challenges currently faced?")

    # Q4: Record-keeping issues
    elif state["step"] == "q4":
        state["data"]["record_keeping_issues"] = msg_text
        state["step"] = "q5"
        send_wa_message(user_phone,
            "Preferred language?\n"
            "1 = English\n"
            "2 = Shona\n"
            "3 = Ndebele"
        )

    # Q5: Language - with validation + FINAL SAVE
    elif state["step"] == "q5":
        lang_options = {"1": "English", "2": "Shona", "3": "Ndebele"}
        if msg_text in lang_options:
            state["data"]["preferred_language"] = lang_options[msg_text]
            state["data"]["phone_number"] = user_phone
            state["data"]["date_joined"] = datetime.now().isoformat()

            # Save to Google Sheets
            try:
                requests.post(SHEETS_URL, json=state["data"], timeout=5)
            except Exception as e:
                print(f"Sheets error: {e}")

            # Final reply
            send_wa_message(user_phone,
                f"Thanks {state['data']['full_name']}! We've recorded your details. "
                "The WOW team will contact you soon."
            )
            state = {"step": "consent", "data": {}} # Reset for next conversation
        else:
            send_wa_message(user_phone, "Please reply 1, 2, or 3")

    user_states[user_phone] = state
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)