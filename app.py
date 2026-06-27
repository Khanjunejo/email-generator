from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
import os
import json
import traceback
import requests
from datetime import datetime

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
CORS(app)
app.secret_key = os.environ.get ("SECRET_KEY", "")

# ============================
# OPENROUTER API
# ============================
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
API_URL = ""
MODEL = ""

def call_ai(prompt, max_tokens=1024):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Email Generator"
    }
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens
    }
    response = requests.post(API_URL, headers=headers, json=body, timeout=30)
    data = response.json()
    print("OpenRouter:", str(data)[:200])
    if "error" in data:
        raise Exception(data["error"].get("message", "OpenRouter error"))
    return data["choices"][0]["message"]["content"].strip()


# ============================
# FILE HELPERS
# ============================
USERS_FILE      = "users.json"
ANALYTICS_FILE  = "analytics.json"
SAVED_FILE      = "saved_emails.json"
SIGNATURE_FILE  = "signatures.json"

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_logged_in():
    return session.get("user") is not None

def current_user_email():
    return session.get("user", {}).get("email", "")

def track(email_type, tone, language):
    a = load_json(ANALYTICS_FILE, {"total":0,"by_type":{},"by_tone":{},"by_language":{},"history":[]})
    a["total"] = a.get("total", 0) + 1
    a["by_type"][email_type]   = a["by_type"].get(email_type, 0) + 1
    a["by_tone"][tone]         = a["by_tone"].get(tone, 0) + 1
    a["by_language"][language] = a["by_language"].get(language, 0) + 1
    a.setdefault("history", []).insert(0, {
        "type": email_type, "tone": tone, "language": language,
        "time": datetime.now().strftime("%d %b %Y %H:%M")
    })
    a["history"] = a["history"][:50]
    save_json(ANALYTICS_FILE, a)


# ============================
# PAGES
# ============================
@app.route("/")
def index():
    if not is_logged_in(): return redirect(url_for("login"))
    return render_template("index.html", user=session.get("user"))

@app.route("/login")
def login():
    if is_logged_in(): return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/signup")
def signup():
    if is_logged_in(): return redirect(url_for("index"))
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/saved")
def saved_page():
    if not is_logged_in(): return redirect(url_for("login"))
    return render_template("saved.html", user=session.get("user"))


# ============================
# AUTH
# ============================
@app.route("/api/signup", methods=["POST"])
def api_signup():
    try:
        data       = request.json
        first_name = data.get("first_name","").strip()
        last_name  = data.get("last_name","").strip()
        email      = data.get("email","").strip().lower()
        password   = data.get("password","").strip()
        if not all([first_name, last_name, email, password]):
            return jsonify({"success":False,"error":"All fields are required"}), 400
        users = load_json(USERS_FILE, {})
        if email in users:
            return jsonify({"success":False,"error":"Email already registered"}), 400
        users[email] = {"first_name":first_name,"last_name":last_name,
                        "email":email,"password":password,
                        "avatar":first_name[0].upper()+last_name[0].upper()}
        save_json(USERS_FILE, users)
        session["user"] = {"name":first_name+" "+last_name,"email":email,
                           "avatar":first_name[0].upper()+last_name[0].upper()}
        return jsonify({"success":True,"redirect":"/"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500

@app.route("/api/login", methods=["POST"])
def api_login():
    try:
        data     = request.json
        email    = data.get("email","").strip().lower()
        password = data.get("password","").strip()
        if not email or not password:
            return jsonify({"success":False,"error":"Email and password required"}), 400
        users = load_json(USERS_FILE, {})
        user  = users.get(email)
        if not user or user["password"] != password:
            return jsonify({"success":False,"error":"Invalid email or password"}), 401
        session["user"] = {"name":user["first_name"]+" "+user["last_name"],
                           "email":email,"avatar":user["avatar"]}
        return jsonify({"success":True,"redirect":"/"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500

@app.route("/api/google-auth", methods=["POST"])
def google_auth():
    try:
        data   = request.json
        name   = data.get("name","Google User")
        email  = data.get("email","")
        if not email:
            return jsonify({"success":False,"error":"No email"}), 400
        users  = load_json(USERS_FILE, {})
        parts  = name.split(" ",1)
        first  = parts[0]; last = parts[1] if len(parts)>1 else ""
        avatar = (first[0]+(last[0] if last else "")).upper()
        if email not in users:
            users[email] = {"first_name":first,"last_name":last,
                            "email":email,"password":"","avatar":avatar}
            save_json(USERS_FILE, users)
        session["user"] = {"name":name,"email":email,"avatar":avatar}
        return jsonify({"success":True,"redirect":"/"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# AI PROXY
# ============================
@app.route("/claude", methods=["POST"])
def claude_proxy():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        prompt = request.json.get("prompt","")
        result = call_ai(prompt)
        return jsonify({"success":True,"result":result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# GENERATE EMAIL
# ============================
@app.route("/generate-email", methods=["POST"])
def generate_email():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data         = request.json
        email_type   = data.get("email_type","Professional")
        tone         = data.get("tone","Formal")
        length       = data.get("length","Medium")
        recipient    = data.get("recipient","")
        sender       = data.get("sender","")
        context      = data.get("context","")
        subject_hint = data.get("subject_hint","")
        language     = data.get("language","English")

        # Get user signature
        user_email = current_user_email()
        sigs = load_json(SIGNATURE_FILE, {})
        sig  = sigs.get(user_email, {})
        sig_text = ""
        if sig.get("name"):
            sig_text = "\n\nInclude this signature at the end of the email:\n"
            if sig.get("name"):    sig_text += f"{sig['name']}\n"
            if sig.get("title"):   sig_text += f"{sig['title']}\n"
            if sig.get("company"): sig_text += f"{sig['company']}\n"
            if sig.get("phone"):   sig_text += f"📞 {sig['phone']}\n"
            if sig.get("email"):   sig_text += f"✉️ {sig['email']}\n"
            if sig.get("website"): sig_text += f"🌐 {sig['website']}\n"

        length_map = {"Short":"around 100 words","Medium":"around 200 words","Long":"around 350 words"}
        word_count = length_map.get(length,"around 200 words")
        lang_instruction = f"Write the entire email (subject and body) in {language} language." if language != "English" else ""

        prompt = f"""You are an expert email writer. Write a {email_type} email with a {tone} tone.
{lang_instruction}
Details:
- Recipient: {recipient if recipient else 'Not specified'}
- Sender: {sender if sender else 'Not specified'}
- Subject hint: {subject_hint if subject_hint else 'Generate a suitable subject'}
- Context: {context}
- Length: {word_count}
{sig_text}

Return in this EXACT format:
SUBJECT: <subject line>
---
<email body>

No extra commentary. No markdown."""

        full_text = call_ai(prompt)
        if "---" in full_text:
            parts   = full_text.split("---",1)
            subject = parts[0].replace("SUBJECT:","").strip()
            body    = parts[1].strip()
        else:
            lines   = full_text.split("\n")
            subject = lines[0].replace("SUBJECT:","").strip()
            body    = "\n".join(lines[1:]).strip()

        track(email_type, tone, language)
        return jsonify({"success":True,"subject":subject,"body":body})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# GENERATE SUBJECT
# ============================
@app.route("/generate-subject", methods=["POST"])
def generate_subject():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data       = request.json
        context    = data.get("context","")
        email_type = data.get("email_type","Professional")
        prompt     = f"Generate 5 catchy email subject lines for a {email_type} email about: {context}. One per line, no numbering."
        result     = call_ai(prompt, max_tokens=300)
        subjects   = [s.strip() for s in result.split("\n") if s.strip()]
        return jsonify({"success":True,"subjects":subjects[:5]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# ANALYTICS
# ============================
@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        a = load_json(ANALYTICS_FILE, {"total":0,"by_type":{},"by_tone":{},"by_language":{},"history":[]})
        return jsonify({"success":True,"analytics":a})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# SAVE EMAILS
# ============================
@app.route("/api/save-email", methods=["POST"])
def save_email():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data       = request.json
        user_email = current_user_email()
        saved      = load_json(SAVED_FILE, {})
        if user_email not in saved: saved[user_email] = []
        email_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        saved[user_email].insert(0, {
            "id":       email_id,
            "subject":  data.get("subject",""),
            "body":     data.get("body",""),
            "type":     data.get("email_type","Professional"),
            "tone":     data.get("tone","Formal"),
            "language": data.get("language","English"),
            "saved_at": datetime.now().strftime("%d %b %Y %H:%M")
        })
        save_json(SAVED_FILE, saved)
        return jsonify({"success":True,"id":email_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500

@app.route("/api/get-saved", methods=["GET"])
def get_saved():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        saved = load_json(SAVED_FILE, {})
        return jsonify({"success":True,"emails":saved.get(current_user_email(),[])})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)}), 500

@app.route("/api/delete-email/<email_id>", methods=["DELETE"])
def delete_email(email_id):
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        user_email = current_user_email()
        saved      = load_json(SAVED_FILE, {})
        if user_email in saved:
            saved[user_email] = [e for e in saved[user_email] if e["id"] != email_id]
            save_json(SAVED_FILE, saved)
        return jsonify({"success":True})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# TRANSLATE EMAIL
# ============================
@app.route("/api/translate", methods=["POST"])
def translate_email():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data        = request.json
        text        = data.get("text","")
        target_lang = data.get("target_language","English")
        prompt = f"Translate the following email to {target_lang}. Keep same format and tone. Return ONLY the translated text.\n\n{text}"
        result = call_ai(prompt, max_tokens=1024)
        return jsonify({"success":True,"translated":result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# SIGNATURE
# ============================
@app.route("/api/save-signature", methods=["POST"])
def save_signature():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data       = request.json
        user_email = current_user_email()
        sigs       = load_json(SIGNATURE_FILE, {})
        sigs[user_email] = {
            "name":    data.get("name","").strip(),
            "title":   data.get("title","").strip(),
            "company": data.get("company","").strip(),
            "phone":   data.get("phone","").strip(),
            "email":   data.get("sig_email","").strip(),
            "website": data.get("website","").strip()
        }
        save_json(SIGNATURE_FILE, sigs)
        return jsonify({"success":True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500

@app.route("/api/get-signature", methods=["GET"])
def get_signature():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        sigs = load_json(SIGNATURE_FILE, {})
        sig  = sigs.get(current_user_email(), {})
        return jsonify({"success":True,"signature":sig})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# TONE CHECKER
# ============================
@app.route("/api/check-tone", methods=["POST"])
def check_tone():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data  = request.json
        email = data.get("email","")
        prompt = f"""Analyze the tone of this email and give feedback.

Email:
{email}

Return your response in this EXACT format:
TONE: <detected tone in 2-3 words>
SCORE: <score out of 10>
SUMMARY: <one sentence summary of tone>
ISSUES: <list any tone issues, or write "None">
SUGGESTION: <one specific improvement suggestion>

Be concise and helpful."""

        result = call_ai(prompt, max_tokens=400)
        return jsonify({"success":True,"result":result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


# ============================
# EMAIL SUMMARIZER
# ============================
@app.route("/api/summarize", methods=["POST"])
def summarize_email():
    if not is_logged_in(): return jsonify({"success":False,"error":"Not logged in"}), 401
    try:
        data  = request.json
        email = data.get("email","")
        prompt = f"""Summarize this email in 3 bullet points. Be very concise.

Email:
{email}

Return in this EXACT format:
• <point 1>
• <point 2>
• <point 3>
ACTION: <what action is needed, or write "No action needed">

No extra text."""

        result = call_ai(prompt, max_tokens=300)
        return jsonify({"success":True,"result":result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success":False,"error":str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
