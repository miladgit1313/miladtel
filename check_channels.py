import os
import json
import time
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]          # مقصد ارسال پست‌های جدید (گروه/کانال)
OWNER_ID = int(os.environ["OWNER_ID"])   # فقط این یوزر حق مدیریت کانال‌ها رو داره

CHANNELS_FILE = "channels.json"
STATE_FILE = "state.json"
BOT_STATE_FILE = "bot_state.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def tg_call(method, **params):
    resp = requests.post(f"{API}/{method}", data=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_message(chat_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "text": text}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return tg_call("sendMessage", **params)


def answer_callback(callback_id, text=None):
    params = {"callback_query_id": callback_id}
    if text:
        params["text"] = text
    return tg_call("answerCallbackQuery", **params)


def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "➕ افزودن کانال", "callback_data": "add"}],
            [{"text": "➖ حذف کانال", "callback_data": "remove_menu"}],
            [{"text": "📋 لیست کانال‌ها", "callback_data": "list"}],
        ]
    }


def remove_keyboard(channels):
    rows = [[{"text": f"❌ {c}", "callback_data": f"del:{c}"}] for c in channels]
    rows.append([{"text": "🔙 بازگشت", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def handle_updates(channels, bot_state):
    offset = bot_state.get("last_update_id", 0) + 1
    updates = tg_call("getUpdates", offset=offset, timeout=0)["result"]

    for update in updates:
        bot_state["last_update_id"] = update["update_id"]

        # --- پیام متنی ---
        if "message" in update:
            msg = update["message"]
            user_id = msg["from"]["id"]
            chat_id = msg["chat"]["id"]

            if user_id != OWNER_ID:
                continue  # فقط صاحب ربات اجازه‌ی مدیریت داره

            text = (msg.get("text") or "").strip()

            if text in ("/start", "/manage"):
                bot_state["pending"] = None
                send_message(chat_id, "چی‌کار می‌خوای بکنی؟", main_menu_keyboard())

            elif bot_state.get("pending") == "awaiting_add":
                username = text.lstrip("@").strip()
                if username and username not in channels:
                    channels.append(username)
                    send_message(chat_id, f"✅ کانال «{username}» اضافه شد.", main_menu_keyboard())
                elif username in channels:
                    send_message(chat_id, "این کانال از قبل توی لیست هست.", main_menu_keyboard())
                else:
                    send_message(chat_id, "یوزرنیم نامعتبره، دوباره بفرست.")
                bot_state["pending"] = None

        # --- تپ روی دکمه ---
        elif "callback_query" in update:
            cq = update["callback_query"]
            user_id = cq["from"]["id"]
            chat_id = cq["message"]["chat"]["id"]
            data = cq["data"]

            answer_callback(cq["id"])

            if user_id != OWNER_ID:
                continue

            if data == "menu":
                bot_state["pending"] = None
                send_message(chat_id, "چی‌کار می‌خوای بکنی؟", main_menu_keyboard())

            elif data == "add":
                bot_state["pending"] = "awaiting_add"
                send_message(chat_id, "یوزرنیم کانال رو بدون @ بفرست:")

            elif data == "remove_menu":
                if not channels:
                    send_message(chat_id, "لیست کانال‌ها خالیه.", main_menu_keyboard())
                else:
                    send_message(chat_id, "کدوم کانال حذف بشه؟", remove_keyboard(channels))

            elif data == "list":
                if channels:
                    text = "📋 کانال‌های فعلی:\n" + "\n".join(f"• {c}" for c in channels)
                else:
                    text = "لیست کانال‌ها خالیه."
                send_message(chat_id, text, main_menu_keyboard())

            elif data.startswith("del:"):
                username = data.split(":", 1)[1]
                if username in channels:
                    channels.remove(username)
                    send_message(chat_id, f"🗑 کانال «{username}» حذف شد.", main_menu_keyboard())

    return channels, bot_state


def fetch_channel_posts(username):
    """گرفتن پست‌های اخیر یک کانال عمومی از پیش‌نمایش وب تلگرام."""
    url = f"https://t.me/s/{username}"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    posts = []
    for wrap in soup.select("div.tgme_widget_message"):
        data_post = wrap.get("data-post")
        if not data_post:
            continue
        try:
            post_id = int(data_post.split("/")[-1])
        except ValueError:
            continue
        text_div = wrap.select_one(".tgme_widget_message_text")
        text = text_div.get_text("\n", strip=True) if text_div else ""
        posts.append({"id": post_id, "text": text, "link": f"https://t.me/{username}/{post_id}"})

    posts.sort(key=lambda p: p["id"])
    return posts


def check_channels(channels, state):
    for username in channels:
        try:
            posts = fetch_channel_posts(username)
        except Exception as e:
            print(f"[warn] خطا در گرفتن کانال {username}: {e}")
            continue

        if not posts:
            continue

        last_id = state.get(username)

        if last_id is None:
            state[username] = posts[-1]["id"]
            print(f"[init] کانال {username} ثبت شد (baseline: {posts[-1]['id']})")
            continue

        new_posts = [p for p in posts if p["id"] > last_id]

        for post in new_posts:
            snippet = post["text"][:500] if post["text"] else "(پست بدون متن — عکس/ویدیو/فایل)"
            message = f"📢 {username}\n\n{snippet}\n\n{post['link']}"
            try:
                send_message(CHAT_ID, message)
                print(f"[sent] پست جدید از {username}: {post['id']}")
                time.sleep(1)
            except Exception as e:
                print(f"[warn] خطا در ارسال پست {post['id']} از {username}: {e}")

        state[username] = max(p["id"] for p in posts)

    return state


def main():
    channels = load_json(CHANNELS_FILE, [])
    state = load_json(STATE_FILE, {})
    bot_state = load_json(BOT_STATE_FILE, {"last_update_id": 0, "pending": None})

    channels, bot_state = handle_updates(channels, bot_state)
    state = check_channels(channels, state)

    save_json(CHANNELS_FILE, channels)
    save_json(STATE_FILE, state)
    save_json(BOT_STATE_FILE, bot_state)


if __name__ == "__main__":
    main()
