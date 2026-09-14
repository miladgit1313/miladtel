import os
import json
import time
import requests
from bs4 import BeautifulSoup


BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
OWNER_ID = int(os.environ["OWNER_ID"])

CHANNELS_FILE = "channels.json"
STATE_FILE = "state.json"
BOT_STATE_FILE = "bot_state.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


HELP_TEXT = (
    "دستورات:\n"
    "/add username — افزودن کانال (بدون @)\n"
    "/remove username — حذف کانال\n"
    "/list — نمایش لیست کانال‌ها\n"
    "/help — نمایش همین راهنما"
)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def tg_call(method, **params):
    resp = requests.post(
        f"{API}/{method}",
        data=params,
        timeout=15
    )

    resp.raise_for_status()
    return resp.json()


def send_message(chat_id, text):
    return tg_call(
        "sendMessage",
        chat_id=chat_id,
        text=text
    )


def handle_updates(channels, bot_state):
    offset = bot_state.get("last_update_id", 0) + 1

    updates = tg_call(
        "getUpdates",
        offset=offset,
        timeout=0
    )["result"]

    for update in updates:

        bot_state["last_update_id"] = update["update_id"]

        msg = update.get("message")

        if not msg:
            continue

        user_id = msg["from"]["id"]
        chat_id = msg["chat"]["id"]

        if user_id != OWNER_ID:
            continue

        text = (msg.get("text") or "").strip()

        if not text:
            continue

        parts = text.split(maxsplit=1)

        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # -------------------------
        # Help
        # -------------------------

        if command in ("/start", "/help", "/manage"):

            send_message(
                chat_id,
                HELP_TEXT
            )

        # -------------------------
        # Add channel
        # -------------------------

        elif command == "/add":

            username = arg.lstrip("@").strip()

            if not username:

                send_message(
                    chat_id,
                    "یوزرنیم رو هم بنویس، مثلاً:\n/add shiraz"
                )

            elif username in channels:

                send_message(
                    chat_id,
                    "این کانال از قبل توی لیست هست."
                )

            else:

                channels.append(username)

                send_message(
                    chat_id,
                    f"✅ کانال «{username}» اضافه شد."
                )

        # -------------------------
        # Remove channel
        # -------------------------

        elif command == "/remove":

            username = arg.lstrip("@").strip()

            if username in channels:

                channels.remove(username)

                send_message(
                    chat_id,
                    f"🗑 کانال «{username}» حذف شد."
                )

            else:

                send_message(
                    chat_id,
                    "همچین کانالی توی لیست نیست."
                )

        # -------------------------
        # List channels
        # -------------------------

        elif command == "/list":

            if channels:

                send_message(
                    chat_id,
                    "📋 کانال‌های فعلی:\n"
                    + "\n".join(
                        f"• {c}" for c in channels
                    )
                )

            else:

                send_message(
                    chat_id,
                    "لیست کانال‌ها خالیه."
                )

        # -------------------------
        # Unknown command
        # -------------------------

        else:

            send_message(
                chat_id,
                "دستور شناخته‌نشد.\n\n" + HELP_TEXT
            )

    return channels, bot_state


def fetch_channel_posts(username):

    url = f"https://t.me/s/{username}"

    resp = requests.get(
        url,
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    resp.raise_for_status()

    soup = BeautifulSoup(
        resp.text,
        "html.parser"
    )

    posts = []

    for wrap in soup.select(
        "div.tgme_widget_message"
    ):

        data_post = wrap.get("data-post")

        if not data_post:
            continue

        try:

            post_id = int(
                data_post.split("/")[-1]
            )

        except ValueError:

            continue

        text_div = wrap.select_one(
            ".tgme_widget_message_text"
        )

        text = (
            text_div.get_text(
                "\n",
                strip=True
            )
            if text_div
            else ""
        )

        posts.append(
            {
                "id": post_id,
                "text": text,
                "link": f"https://t.me/{username}/{post_id}"
            }
        )

    posts.sort(
        key=lambda p: p["id"]
    )

    return posts


def check_channels(channels, state):

    for username in channels:

        try:

            posts = fetch_channel_posts(
                username
            )

        except Exception as e:

            print(
                f"[warn] خطا در گرفتن کانال "
                f"{username}: {e}"
            )

            continue

        if not posts:
            continue

        last_id = state.get(username)

        # اولین اجرا؛ آخرین پست را فقط ثبت می‌کنیم
        if last_id is None:

            state[username] = posts[-1]["id"]

            print(
                f"[init] کانال {username} ثبت شد "
                f"(baseline: {posts[-1]['id']})"
            )

            continue

        new_posts = [
            p for p in posts
            if p["id"] > last_id
        ]

        for post in new_posts:

            snippet = (
                post["text"][:500]
                if post["text"]
                else "(پست بدون متن — عکس/ویدیو/فایل)"
            )

            message = (
                f"📢 {username}\n\n"
                f"{snippet}\n\n"
                f"{post['link']}"
            )

            try:

                send_message(
                    CHAT_ID,
                    message
                )

                print(
                    f"[sent] پست جدید از "
                    f"{username}: {post['id']}"
                )

                time.sleep(1)

            except Exception as e:

                print(
                    f"[warn] خطا در ارسال پست "
                    f"{post['id']} از {username}: {e}"
                )

        state[username] = max(
            p["id"] for p in posts
        )

    return state


def main():

    channels = load_json(
        CHANNELS_FILE,
        []
    )

    state = load_json(
        STATE_FILE,
        {}
    )

    bot_state = load_json(
        BOT_STATE_FILE,
        {
            "last_update_id": 0
        }
    )

    channels, bot_state = handle_updates(
        channels,
        bot_state
    )

    state = check_channels(
        channels,
        state
    )

    save_json(
        CHANNELS_FILE,
        channels
    )

    save_json(
        STATE_FILE,
        state
    )

    save_json(
        BOT_STATE_FILE,
        bot_state
    )


if __name__ == "__main__":
    main()
