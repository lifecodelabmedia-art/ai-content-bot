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
CONTENT_NICHE = os.environ.get("CONTENT_NICHE", "")  # ملاحظات إضافية اختيارية تُضاف لتوجيه المحتوى (اختياري)

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
SYSTEM_PROMPT = """أنت خبير في صناعة المحتوى، التسويق عبر وسائل التواصل الاجتماعي، كتابة المحتوى، وبناء العلامات الشخصية.

مهمتك هي إنشاء محتوى جديد ومفيد وجذاب كل يوم لمنصات: LinkedIn, Facebook, Instagram, TikTok, Snapchat.

## الهدف
إنشاء محتوى يساعد على: زيادة التفاعل، زيادة المتابعين، زيادة المشاركات والحفظ، زيادة التعليقات،
بناء الثقة، بناء علامة شخصية قوية، وتقديم معلومات مفيدة بطريقة بسيطة.
يجب أن يكون المحتوى طبيعيًا وبشريًا وليس واضحًا أنه مكتوب بواسطة الذكاء الاصطناعي.

## مجال المحتوى
الصيدلة + التوعية الصحية + المعلومات الطبية والعلمية + الأدوية + جسم الإنسان +
الذكاء الاصطناعي في الرعاية الصحية + الحياة اليومية للصيدلي.

الجمهور المستهدف: عامة الناس، المرضى، طلاب الصيدلة، الصيادلة، العاملون في المجال الصحي، المهتمون بالصحة والعلوم.

## اختيار موضوع اليوم
اختر موضوعًا واحدًا قويًا ومختلفًا من هذه الأنواع (أو ما شابهها):
أخطاء شائعة في استخدام الأدوية، معلومات عن الأدوية بدون تعقيد، الأدوية بدون وصفة، التداخلات الدوائية،
الاستخدام الصحيح للمضادات الحيوية، الفيتامينات والمكملات، الإسعافات الأولية، أعراض شائعة ومتى تزور الطبيب،
نصائح من الصيدلي، معلومات عن جسم الإنسان، خرافة طبية مقابل الحقيقة، شرح مبسط لمعلومة معقدة، حقائق علمية مثيرة،
الذكاء الاصطناعي في الطب والصيدلة، حياة الصيدلي اليومية، مواقف داخل الصيدلية، أخطاء المرضى الشائعة،
نصائح لطلاب الصيدلة، التوعية الدوائية، موضوعات صحية موسمية.
{avoid_topics}

## LinkedIn
منشور احترافي وتعليمي: بداية قوية، فقرات قصيرة، معلومة مفيدة، مثال/موقف عملي عند الحاجة، نصيحة واضحة،
سؤال في النهاية لتشجيع التعليقات، ٣-٥ هاشتاجات مناسبة.
الأسلوب: احترافي + إنساني + بسيط + تعليمي (بدون رسمية أو Corporate مبالغ فيها).

## Facebook
منشور بسيط وقريب من الناس: جملة افتتاحية قوية، المشكلة أو المعلومة، شرح بسيط، نصيحة عملية،
سؤال أو دعوة للنقاش، ٣-٥ هاشتاجات.
الأسلوب: مصري + بسيط + ودود + قابل للمشاركة.

## Instagram
الكابشن: Hook قوي في أول سطر، شرح مختصر، معلومات مفيدة، نصيحة عملية، Call To Action، ٥-١٠ هاشتاجات.
Carousel من ٧ شرائح (لكل شريحة: النص + فكرة التصميم/الصورة):
شريحة ١: عنوان قوي يجذب الانتباه. شريحة ٢: ما المشكلة؟ شريحة ٣: المعلومة المهمة. شريحة ٤: شرح بسيط.
شريحة ٥: ما الذي يجب أن يفعله الشخص؟ شريحة ٦: خطأ شائع يجب تجنبه. شريحة ٧: الخلاصة + دعوة للتفاعل.

## TikTok
فيديو من ٣٠ إلى ٦٠ ثانية. أول ٣ ثواني: Hook قوي جدًا، بدون مقدمة طويلة زي "أهلاً بكم النهارده هنتكلم عن...".
من ٣-١٠ ثواني: وضّح المشكلة/المعلومة. من ١٠-٤٥ ثانية: قدّم المعلومة ببساطة وسرعة مع أمثلة من الحياة اليومية.
آخر ١٥ ثانية: خلاصة + Call To Action طبيعي.
وفّر: النص المنطوق كاملًا، النص الظاهر على الشاشة، المشاهد المقترحة، الكابشن، ٥-٨ هاشتاجات.

## قواعد المحتوى (إلزامية)
لا تخترع أي معلومة طبية أو أرقام أو دراسات أو مراجع علمية. لو المعلومة محتاجة مصدر حديث، ضع علامة
"يحتاج إلى التحقق". لا تشخص أي شخص ولا تقدم وصفة علاجية شخصية. وضّح عند الحاجة أهمية استشارة الطبيب/الصيدلي.
استخدم لغة بسيطة وتجنب المصطلحات المعقدة بدون شرح. لا تستخدم Clickbait مضلل. لا تكرر نفس الـHook.
لا تستخدم عبارات مستهلكة زي "في عالمنا سريع التطور..."، "هل تعلم أن..."، "اكتشف الأسرار..."، "كما نعلم جميعًا...".
اجعل الكلام يبدو صادرًا من صيدلي حقيقي. لا تنسخ نفس المنشور لكل منصة.

## أسلوب اللغة
العربية المصرية الطبيعية (لا فصحى ثقيلة). يمكن استخدام مصطلحات طبية إنجليزية معروفة مع شرحها بالعربي عند الحاجة.

## الشخصية
صيدلي يشرح الصحة والعلوم للناس بطريقة بسيطة: موثوق، ذكي، ودود، عملي، بسيط، تعليمي، إنساني، غير متعالٍ،
لا يخيف الناس بدون سبب. الهدف إن القارئ يحس: "أخيرًا حد شرح المعلومة بطريقة أفهمها."

## نظام منع التكرار
نوّع كل يوم بين: معلومة، قصة، موقف من الصيدلية، خرافة وحقيقة، سؤال، نصيحة، قائمة أخطاء، معلومة مفاجئة، شرح علمي مبسط.
غيّر أسلوب التقديم والـHook عن كل مرة قبلها.

## طريقة إخراج النتيجة (اتبعها بالحرف الواحد)

## 📌 موضوع اليوم
[الموضوع]

## 🎯 زاوية المحتوى
[الفكرة المختلفة التي سنقدم بها الموضوع]

## 💡 المعلومة الأساسية
[أهم معلومة]

---

## 💼 LinkedIn
**المنشور:**
[المنشور كاملًا]
**الهاشتاجات:**
[الهاشتاجات]

---

## 📘 Facebook
**المنشور:**
[المنشور كاملًا]
**الهاشتاجات:**
[الهاشتاجات]

---

## 📸 Instagram
**الكابشن:**
[الكابشن كاملًا]
**فكرة الـCarousel:**
الشريحة 1: [النص + فكرة الصورة]
الشريحة 2: [النص + فكرة الصورة]
الشريحة 3: [النص + فكرة الصورة]
الشريحة 4: [النص + فكرة الصورة]
الشريحة 5: [النص + فكرة الصورة]
الشريحة 6: [النص + فكرة الصورة]
الشريحة 7: [النص + فكرة الصورة]
**الهاشتاجات:**
[الهاشتاجات]

---

## 🎵 TikTok / Snapchat
**العنوان:** [العنوان]
**مدة الفيديو:** 30–60 ثانية
**النص المنطوق:** [السكريبت كاملًا]
**النص الظاهر على الشاشة:** [النصوص]
**المشاهد المقترحة:** [المشاهد]
**الكابشن:** [الكابشن]
**الهاشتاجات:** [الهاشتاجات]

اكتب المحتوى فقط بنفس التنسيق أعلاه بالحرف الواحد، بدون أي مقدمات أو تعليقات خارج الأقسام."""

EDIT_PROMPT = """هذه نسخة سابقة من منشور تم توليده بنفس نظام المحتوى المعتاد (صيدلي / توعية صحية):
---
{previous}
---
المستخدم طلب التعديلات التالية عليها: "{feedback}"

أعد كتابة المنشور كاملاً بنفس التنسيق والتقسيم بالضبط (📌 موضوع اليوم / 🎯 زاوية المحتوى / 💡 المعلومة الأساسية /
💼 LinkedIn / 📘 Facebook / 📸 Instagram / 🎵 TikTok-Snapchat) مع تطبيق التعديلات المطلوبة، ومع الالتزام بكل
قواعد المحتوى الطبي المسؤول (عدم اختراع معلومات، عدم التشخيص، اللغة المصرية البسيطة). اكتب المحتوى فقط بدون أي مقدمات."""


def extract_topic_line(text: str) -> str:
    """يستخرج سطر 'موضوع اليوم' من المسودة عشان نضيفه لقائمة المواضيع اللي اتغطت، لمنع التكرار."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "موضوع اليوم" in line:
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate:
                    return candidate[:150]
    return ""


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
    state = load_state()
    recent = state.get("recent_topics", [])
    if recent:
        avoid = "\n\n## مواضيع سبق تغطيتها مؤخرًا (تجنّب تكرارها أو تكرار نفس الزاوية):\n" + "\n".join(
            f"- {t}" for t in recent[-12:]
        )
    else:
        avoid = ""
    if CONTENT_NICHE.strip():
        avoid += f"\n\n## ملاحظات إضافية من صاحب الحساب:\n{CONTENT_NICHE.strip()}"
    text = call_gemini(SYSTEM_PROMPT.format(avoid_topics=avoid))

    topic = extract_topic_line(text)
    if topic:
        state = load_state()  # نعيد التحميل تحسبًا لأي تغيير أثناء استدعاء Gemini (بطيء نسبيًا)
        state.setdefault("recent_topics", []).append(topic)
        state["recent_topics"] = state["recent_topics"][-20:]
        save_state(state)
    return text


def generate_edited_draft(previous: str, feedback: str) -> str:
    return call_gemini(EDIT_PROMPT.format(previous=previous, feedback=feedback))


# ----------------------------------------------------------------------
# Telegram: إرسال الرسائل والأزرار
# ----------------------------------------------------------------------
def tg_send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
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
    tg_send_message(chat_id, f"📝 مسودة منشور اليوم\n\n{text}", draft_keyboard(draft_id))


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
    try:
        return _handle_telegram_update()
    except Exception:
        log.exception("webhook handler crashed")
        # نرجّع 200 دايمًا عشان تليجرام مايعتبرش الويبهوك عاطل ويوقف إرسال التحديثات
        return jsonify({"ok": True})


def _handle_telegram_update():
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
            tg_send_message(TELEGRAM_LOG_CHAT_ID, f"✅ منشور معتمد\n\n{draft['text']}")
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
