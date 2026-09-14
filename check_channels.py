import os
import json
import time
import re
import mimetypes
import tempfile

import requests
from bs4 import BeautifulSoup


BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
OWNER_ID = int(os.environ["OWNER_ID"])

CHANNELS_FILE = "channels.json"
STATE_FILE = "state.json"
BOT_STATE_FILE = "bot_state.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


HELP_TEXT = (
    "🤖 مدیریت ربات ارسال پست\n\n"
    "/add username — افزودن کانال\n"
    "/remove username — حذف کانال\n"
    "/list — نمایش کانال‌ها\n"
    "/help — راهنما\n\n"
    "مثال:\n"
    "/add shiraz\n"
    "/remove shiraz"
)


# =========================================================
# JSON
# =========================================================

def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] خطا در خواندن {path}: {e}")
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# TELEGRAM API
# =========================================================

def tg_call(method, **params):
    response = requests.post(
        f"{API}/{method}",
        data=params,
        timeout=60
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise Exception(
            result.get(
                "description",
                "Telegram API error"
            )
        )

    return result


def send_message(chat_id, text):
    return tg_call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        disable_web_page_preview=False
    )


# =========================================================
# CHANNEL PAGE
# =========================================================

def fetch_channel_posts(username):

    username = username.strip().lstrip("@")

    url = f"https://t.me/s/{username}"

    print(f"[FETCH] {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=60
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
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
            channel_name, post_id_text = (
                data_post.rsplit("/", 1)
            )

            post_id = int(post_id_text)

        except Exception:
            continue

        # -------------------------
        # TEXT / CAPTION
        # -------------------------

        text_div = wrap.select_one(
            ".tgme_widget_message_text"
        )

        text = ""

        if text_div:
            text = text_div.get_text(
                "\n",
                strip=True
            )

        # -------------------------
        # POST LINK
        # -------------------------

        link = (
            f"https://t.me/"
            f"{channel_name}/"
            f"{post_id}"
        )

        # -------------------------
        # PHOTO
        # -------------------------

        media = []

        photo_nodes = wrap.select(
            "a.tgme_widget_message_photo_wrap"
        )

        for photo in photo_nodes:

            style = photo.get(
                "style",
                ""
            )

            match = re.search(
                r"background-image:\s*url\(['\"]?([^'\")]+)",
                style
            )

            if match:

                media_url = match.group(1)

                media.append({
                    "type": "photo",
                    "url": media_url
                })

        # -------------------------
        # VIDEO
        # -------------------------

        video = wrap.select_one(
            "video"
        )

        if video:

            source = video.select_one(
                "source"
            )

            video_url = None

            if source:
                video_url = source.get("src")

            if not video_url:
                video_url = video.get("src")

            if video_url:

                media.append({
                    "type": "video",
                    "url": video_url
                })

        # -------------------------
        # DOCUMENT / FILE
        # -------------------------

        document_node = wrap.select_one(
            ".tgme_widget_message_document"
        )

        if document_node:

            document_link = document_node.get(
                "href"
            )

            if document_link:

                media.append({
                    "type": "document",
                    "url": document_link
                })

        posts.append({
            "id": post_id,
            "text": text,
            "link": link,
            "media": media
        })

    posts.sort(
        key=lambda x: x["id"]
    )

    return posts


# =========================================================
# DOWNLOAD MEDIA
# =========================================================

def download_media(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=120,
        stream=True
    )

    response.raise_for_status()

    content_type = (
        response.headers
        .get("content-type", "")
        .split(";")[0]
        .lower()
    )

    extension = (
        mimetypes.guess_extension(
            content_type
        )
        or ".bin"
    )

    temp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=extension
    )

    try:

        for chunk in response.iter_content(
            chunk_size=1024 * 1024
        ):

            if chunk:
                temp.write(chunk)

        temp.close()

        return (
            temp.name,
            content_type
        )

    except Exception:

        temp.close()

        try:
            os.remove(temp.name)
        except Exception:
            pass

        raise


# =========================================================
# SEND PHOTO
# =========================================================

def send_photo(
    chat_id,
    file_path,
    caption=""
):

    with open(
        file_path,
        "rb"
    ) as f:

        return tg_call(
            "sendPhoto",
            chat_id=chat_id,
            photo=f,
            caption=caption[:1024]
        )


# =========================================================
# SEND VIDEO
# =========================================================

def send_video(
    chat_id,
    file_path,
    caption=""
):

    with open(
        file_path,
        "rb"
    ) as f:

        return tg_call(
            "sendVideo",
            chat_id=chat_id,
            video=f,
            caption=caption[:1024],
            supports_streaming=True
        )


# =========================================================
# SEND DOCUMENT
# =========================================================

def send_document(
    chat_id,
    file_path,
    caption=""
):

    with open(
        file_path,
        "rb"
    ) as f:

        return tg_call(
            "sendDocument",
            chat_id=chat_id,
            document=f,
            caption=caption[:1024]
        )


# =========================================================
# SEND POST
# =========================================================

def send_post(post, username):

    text = post.get(
        "text",
        ""
    ).strip()

    link = post.get(
        "link",
        ""
    )

    media = post.get(
        "media",
        []
    )

    print(
        f"[SEND] @{username} "
        f"post={post['id']} "
        f"media={len(media)}"
    )

    # =====================================================
    # NO MEDIA
    # =====================================================

    if not media:

        message = (
            f"📢 @{username}\n\n"
            f"{text}\n\n"
            f"🔗 {link}"
        )

        send_message(
            CHAT_ID,
            message[:4096]
        )

        return True

    # =====================================================
    # MEDIA
    # =====================================================

    sent_any = False

    for index, item in enumerate(media):

        media_url = item.get(
            "url"
        )

        media_type = item.get(
            "type"
        )

        if not media_url:
            continue

        temp_path = None

        try:

            print(
                f"[DOWNLOAD] {media_url[:100]}"
            )

            temp_path, content_type = (
                download_media(
                    media_url
                )
            )

            # کپشن فقط روی اولین مدیا
            caption = ""

            if index == 0:

                caption = (
                    f"📢 @{username}\n\n"
                    f"{text}\n\n"
                    f"🔗 {link}"
                )

            if media_type == "photo":

                send_photo(
                    CHAT_ID,
                    temp_path,
                    caption
                )

            elif media_type == "video":

                send_video(
                    CHAT_ID,
                    temp_path,
                    caption
                )

            else:

                send_document(
                    CHAT_ID,
                    temp_path,
                    caption
                )

            sent_any = True

            print(
                f"[OK] مدیا ارسال شد"
            )

            time.sleep(1)

        except Exception as e:

            print(
                f"[ERROR] خطا در ارسال مدیا: {e}"
            )

        finally:

            if temp_path:

                try:
                    os.remove(
                        temp_path
                    )
                except Exception:
                    pass

    # =====================================================
    # IF MEDIA FAILED BUT TEXT EXISTS
    # =====================================================

    if not sent_any:

        message = (
            f"📢 @{username}\n\n"
            f"{text}\n\n"
            f"🔗 {link}"
        )

        send_message(
            CHAT_ID,
            message[:4096]
        )

    return sent_any


# =========================================================
# BOT COMMANDS
# =========================================================

def handle_updates(
    channels,
    bot_state
):

    offset = (
        bot_state.get(
            "last_update_id",
            0
        )
        + 1
    )

    try:

        result = tg_call(
            "getUpdates",
            offset=offset,
            timeout=0
        )

        updates = result.get(
            "result",
            []
        )

    except Exception as e:

        print(
            f"[WARN] خطا در getUpdates: {e}"
        )

        return channels, bot_state

    for update in updates:

        bot_state[
            "last_update_id"
        ] = update["update_id"]

        message = update.get(
            "message"
        )

        if not message:
            continue

        user_id = message.get(
            "from",
            {}
        ).get(
            "id"
        )

        if user_id != OWNER_ID:
            continue

        chat_id = message.get(
            "chat",
            {}
        ).get(
            "id"
        )

        text = (
            message.get(
                "text"
            ) or ""
        ).strip()

        if not text:
            continue

        parts = text.split(
            maxsplit=1
        )

        command = parts[0].lower()

        argument = (
            parts[1].strip()
            if len(parts) > 1
            else ""
        )

        # =================================================
        # HELP
        # =================================================

        if command in (
            "/start",
            "/help",
            "/manage"
        ):

            send_message(
                chat_id,
                HELP_TEXT
            )

        # =================================================
        # ADD
        # =================================================

        elif command == "/add":

            username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            if not username:

                send_message(
                    chat_id,
                    "❌ یوزرنیم کانال را وارد کن.\n\n"
                    "مثال:\n"
                    "/add shiraz"
                )

                continue

            if username in [
                c.lower().lstrip("@")
                for c in channels
            ]:

                send_message(
                    chat_id,
                    f"⚠️ @{username} "
                    f"قبلاً اضافه شده."
                )

                continue

            channels.append(
                username
            )

            send_message(
                chat_id,
                f"✅ کانال @{username} اضافه شد."
            )

            print(
                f"[ADD] @{username}"
            )

        # =================================================
        # REMOVE
        # =================================================

        elif command == "/remove":

            username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            old_count = len(
                channels
            )

            channels = [
                c for c in channels
                if c.lower().lstrip("@")
                != username
            ]

            if len(channels) < old_count:

                send_message(
                    chat_id,
                    f"🗑 @{username} حذف شد."
                )

            else:

                send_message(
                    chat_id,
                    f"❌ @{username} در لیست نیست."
                )

        # =================================================
        # LIST
        # =================================================

        elif command == "/list":

            if not channels:

                send_message(
                    chat_id,
                    "📋 لیست کانال‌ها خالی است."
                )

            else:

                send_message(
                    chat_id,
                    "📋 کانال‌های فعال:\n\n"
                    + "\n".join(
                        f"• @{c}"
                        for c in channels
                    )
                )

        else:

            send_message(
                chat_id,
                "❌ دستور شناخته نشد.\n\n"
                + HELP_TEXT
            )

    return channels, bot_state


# =========================================================
# CHECK CHANNELS
# =========================================================

def check_channels(
    channels,
    state
):

    for username in channels:

        username = (
            username
            .strip()
            .lstrip("@")
        )

        print(
            f"\n[CHECK] @{username}"
        )

        try:

            posts = fetch_channel_posts(
                username
            )

        except Exception as e:

            print(
                f"[ERROR] @{username}: {e}"
            )

            continue

        if not posts:

            print(
                f"[INFO] پستی پیدا نشد."
            )

            continue

        last_id = state.get(
            username
        )

        # =================================================
        # FIRST RUN
        # =================================================

        if last_id is None:

            state[
                username
            ] = posts[-1]["id"]

            print(
                f"[INIT] @{username} "
                f"baseline={posts[-1]['id']}"
            )

            continue

        # =================================================
        # NEW POSTS
        # =================================================

        new_posts = [
            post
            for post in posts
            if post["id"] > last_id
        ]

        if not new_posts:

            print(
                f"[INFO] پست جدیدی نیست."
            )

            continue

        print(
            f"[FOUND] "
            f"{len(new_posts)} پست جدید"
        )

        for post in new_posts:

            try:

                send_post(
                    post,
                    username
                )

                print(
                    f"[SENT] @{username} "
                    f"post={post['id']}"
                )

                # جلوگیری از فشار به Telegram
                time.sleep(2)

            except Exception as e:

                print(
                    f"[ERROR] پست "
                    f"{post['id']}: {e}"
                )

                # اگر ارسال شکست خورد،
                # state جلو نمی‌رود
                break

        else:

            # فقط وقتی همه پست‌ها
            # با موفقیت ارسال شدند
            state[
                username
            ] = max(
                p["id"]
                for p in new_posts
            )

    return state


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print(
        "Telegram Public Channel Forwarder"
    )
    print("=" * 60)

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

    print(
        f"[INFO] تعداد کانال‌ها: "
        f"{len(channels)}"
    )

    # دستورات مدیریت
    channels, bot_state = handle_updates(
        channels,
        bot_state
    )

    # بررسی کانال‌های عمومی
    state = check_channels(
        channels,
        state
    )

    # ذخیره
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

    print("\n[DONE] اجرای برنامه تمام شد.")


if __name__ == "__main__":
    main()
