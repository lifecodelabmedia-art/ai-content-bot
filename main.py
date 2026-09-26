"""
بوت توليد ومراجعة منشورات السوشيال ميديا اليومية
==================================================
يولّد محتوى يوميًا عبر Gemini API، يرسله لك على تليجرام مع أزرار
(موافقة / تعديل / رفض)، ويحفظ المعتمد منها في شات/قناة تليجرام تسجيل دائم.

كل الإعدادات عن طريق متغيرات البيئة (Environment Variables) — راجع README.md
"""

import os
import json
import uuid
import logging
from pathlib import Path

import requests
from flask import Flask, request, jsonify

# ----------------------------------------------------------------------
# الإعدادات (من متغيرات البيئة)
# ----------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]          # شاتك الشخصي (يرسل له المسودات)
TELEGRAM_LOG_CHAT_ID = os.environ.get("TELEGRAM_LOG_CHAT_ID", TELEGRAM_CHAT_ID)  # قناة/شات لتسجيل المعتمد
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GENERATE_SECRET = os.environ["GENERATE_SECRET"]            # مفتاح سري لحماية /generate
WEBHOOK_SECRET_PATH = os.environ["WEBHOOK_SECRET_PATH"]    # جزء سري في رابط الويبهوك
CONTENT_NICHE = os.environ.get("CONTENT_NICHE", "محتوى شخصي / إنفلونسر عام")

DATA_FILE = Path(os.environ.get("DATA_FILE", "data/state.json"))
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GEMINI_API = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("content-bot")

app = Flask(__name__)


# ----------------------------------------------------------------------
# تخزين بسيط في ملف JSON (يكفي للاستخدام الشخصي)
# ----------------------------------------------------------------------
def load_state():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"drafts": {}, "awaiting_edit": {}}


def save_state(state):
    DATA_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# Gemini: توليد / تعديل المحتوى
# ----------------------------------------------------------------------
BASE_PROMPT = """أنت خبير كتابة محتوى لصنّاع محتوى شخصي (إنفلونسر) في مجال: {niche}
اكتب منشور اليوم بالعربية الفصحى البسيطة (يمكن مزجها بعامية خفيفة)، بأسلوب طبيعي وجذاب وصادق،
وقسّمه بعناوين واضحة بالضبط كالتالي:

### LinkedIn
فقرة قصيرة احترافية (٣-٥ أسطر) تحمل رسالة أو خبرة أو درس مستفاد.

### TikTok / Snapchat
سكربت قصير جدًا لفيديو أقل من ٦٠ ثانية: بداية جاذبة (Hook) في جملة واحدة، ثم ٣-٤ نقاط حوارية، ثم خاتمة/دعوة لفعل.

### Instagram / Facebook
كابشن جذاب (٤-٦ أسطر) + ٨-١٠ هاشتاجات مناسبة في النهاية.

### فكرة تصوير أو تصميم
سطر واحد يقترح لقطة أو تصميم بسيط ينفذ بدون معدات احترافية.

اكتب المحتوى فقط بدون أي مقدمات أو شرح أو تعليق خارج الأقسام الأربعة أعلاه."""

EDIT_PROMPT = """هذه نسخة سابقة من منشور تم توليده:
---
{previous}
---
المستخدم طلب التعديلات التالية عليها: "{feedback}"

أعد كتابة المنشور كاملاً بنفس التقسيم بالضبط (LinkedIn / TikTok-Snapchat / Instagram-Facebook / فكرة تصوير أو تصميم)
مع تطبيق التعديلات المطلوبة. اكتب المحتوى فقط بدون أي مقدمات."""


def call_gemini(prompt: str) -> str:
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    resp = requests.post(GEMINI_API, json=payload, headers=headers, timeout=60)
    if not resp.ok:
        # اطبع تفاصيل الخطأ الكاملة من جوجل (بدل رقم الحالة بس) عشان يسهل تشخيصه
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_new_draft() -> str:
    return call_gemini(BASE_PROMPT.format(niche=CONTENT_NICHE))


def generate_edited_draft(previous: str, feedback: str) -> str:
    return call_gemini(EDIT_PROMPT.format(previous=previous, feedback=feedback))


# ----------------------------------------------------------------------
# Telegram: إرسال الرسائل والأزرار
# ----------------------------------------------------------------------
def tg_send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def tg_answer_callback(callback_id, text=""):
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        data={"callback_query_id": callback_id, "text": text},
        timeout=15,
    )


def draft_keyboard(draft_id):
    return {
        "inline_keyboard": [[
            {"text": "🟢 موافقة", "callback_data": f"appr:{draft_id}"},
            {"text": "✏️ تعديل", "callback_data": f"edit:{draft_id}"},
            {"text": "🔴 رفض", "callback_data": f"rej:{draft_id}"},
        ]]
    }


def send_draft(chat_id, draft_id, text):
    tg_send_message(chat_id, f"📝 *مسودة منشور اليوم*\n\n{text}", draft_keyboard(draft_id))


# ----------------------------------------------------------------------
# المسارات (Routes)
# ----------------------------------------------------------------------
@app.get("/")
def health():
    return "OK - content bot is running"


@app.get("/debug-models")
def debug_models():
    """لتشخيص المشاكل: يعرض الموديلات المتاحة فعليًا لمفتاح Gemini بتاعك."""
    if request.args.get("key") != GENERATE_SECRET:
        return jsonify({"error": "unauthorized"}), 403
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    resp = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models", headers=headers, timeout=30
    )
    return jsonify({"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text})


@app.get("/generate")
def generate_endpoint():
    """يستدعيه Cron خارجي (مثل cron-job.org) مرة يوميًا."""
    if request.args.get("key") != GENERATE_SECRET:
        return jsonify({"error": "unauthorized"}), 403

    try:
        text = generate_new_draft()
    except Exception as e:
        log.exception("gemini generation failed")
        tg_send_message(TELEGRAM_CHAT_ID, f"⚠️ فشل توليد منشور اليوم: {e}")
        return jsonify({"error": str(e)}), 500

    state = load_state()
    draft_id = uuid.uuid4().hex[:10]
    state["drafts"][draft_id] = {"text": text, "chat_id": TELEGRAM_CHAT_ID}
    save_state(state)

    send_draft(TELEGRAM_CHAT_ID, draft_id, text)
    return jsonify({"status": "sent", "draft_id": draft_id})


@app.post(f"/telegram-webhook/{WEBHOOK_SECRET_PATH}")
def telegram_webhook():
    update = request.get_json(force=True, silent=True) or {}
    state = load_state()

    # --- ضغطة زرار (موافقة / تعديل / رفض) ---
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        data = cq.get("data", "")
        tg_answer_callback(cq["id"])

        action, _, draft_id = data.partition(":")
        draft = state["drafts"].get(draft_id)
        if not draft:
            tg_send_message(chat_id, "⚠️ المسودة دي مش موجودة أو خلصت صلاحيتها.")
            return jsonify({"ok": True})

        if action == "appr":
            tg_send_message(TELEGRAM_LOG_CHAT_ID, f"✅ *منشور معتمد*\n\n{draft['text']}")
            tg_send_message(chat_id, "تمام، اتحفظ المنشور في شات/قناة الأرشفة ✅")
            state["drafts"].pop(draft_id, None)

        elif action == "rej":
            tg_send_message(chat_id, "تم الرفض 🔴 هطلع لك مسودة جديدة في الميعاد الجاي.")
            state["drafts"].pop(draft_id, None)

        elif action == "edit":
            state["awaiting_edit"][str(chat_id)] = draft_id
            tg_send_message(chat_id, "اكتب ملاحظاتك على المسودة دي وهعيد صياغتها ✏️")

        save_state(state)
        return jsonify({"ok": True})

    # --- رسالة نصية عادية (ممكن تكون ملاحظات تعديل، أو أمر يدوي) ---
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text_in = update["message"]["text"].strip()

        if text_in == "/generate":
            try:
                text = generate_new_draft()
            except Exception as e:
                tg_send_message(chat_id, f"⚠️ فشل التوليد: {e}")
                return jsonify({"ok": True})
            draft_id = uuid.uuid4().hex[:10]
            state["drafts"][draft_id] = {"text": text, "chat_id": chat_id}
            save_state(state)
            send_draft(chat_id, draft_id, text)
            return jsonify({"ok": True})

        pending_draft_id = state["awaiting_edit"].get(str(chat_id))
        if pending_draft_id and pending_draft_id in state["drafts"]:
            previous = state["drafts"][pending_draft_id]["text"]
            try:
                new_text = generate_edited_draft(previous, text_in)
            except Exception as e:
                tg_send_message(chat_id, f"⚠️ فشل التعديل: {e}")
                return jsonify({"ok": True})

            state["drafts"][pending_draft_id]["text"] = new_text
            state["awaiting_edit"].pop(str(chat_id), None)
            save_state(state)
            send_draft(chat_id, pending_draft_id, new_text)
            return jsonify({"ok": True})

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
