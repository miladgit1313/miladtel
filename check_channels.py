import os
import json
import time
import re
import requests
from bs4 import BeautifulSoup


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"].strip()
OWNER_ID = int(os.environ["OWNER_ID"])

CHANNELS_FILE = "channels.json"
STATE_FILE = "state.json"
BOT_STATE_FILE = "bot_state.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


HELP_TEXT = (
    "🤖 ربات ارسال پست\n\n"
    "/add username - افزودن کانال\n"
    "/remove username - حذف کانال\n"
    "/list - لیست کانال‌ها\n"
    "/id - نمایش شناسه چت فعلی\n"
    "/help - راهنما"
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

        print(f"[ERROR] خواندن {path}: {e}")

        return default


def save_json(path, data):

    with open(path, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_call(method, **params):

    url = f"{API}/{method}"

    try:

        response = requests.post(
            url,
            data=params,
            timeout=60
        )

    except requests.RequestException as e:

        raise Exception(
            f"Network error: {e}"
        )

    # پاسخ Telegram را اول بخوان
    try:

        result = response.json()

    except Exception:

        raise Exception(
            f"Telegram returned HTTP "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    # خطای واقعی Telegram
    if not result.get("ok"):

        description = result.get(
            "description",
            "Unknown Telegram error"
        )

        error_code = result.get(
            "error_code",
            response.status_code
        )

        raise Exception(
            f"Telegram API error "
            f"{error_code}: {description}"
        )

    return result


# =========================================================
# TEST DESTINATION
# =========================================================

def test_destination():

    print("")
    print("=" * 60)
    print("TESTING DESTINATION CHAT")
    print("=" * 60)

    print(
        f"[INFO] CHAT_ID = {CHAT_ID}"
    )

    try:

        result = telegram_call(
            "getChat",
            chat_id=CHAT_ID
        )

        chat = result.get(
            "result",
            {}
        )

        print("")
        print("[OK] مقصد پیدا شد.")

        print(
            f"[CHAT ID] {chat.get('id')}"
        )

        print(
            f"[CHAT TYPE] {chat.get('type')}"
        )

        print(
            f"[CHAT TITLE] {chat.get('title')}"
        )

        if chat.get("username"):

            print(
                f"[CHAT USERNAME] "
                f"@{chat.get('username')}"
            )

        print("=" * 60)

        return True

    except Exception as e:

        print("")
        print("[FATAL] مقصد Telegram مشکل دارد.")
        print(f"[DETAIL] {e}")

        print("")
        print(
            "CHAT_ID باید شناسه واقعی گروه باشد، "
            "مثلاً -1001234567890"
        )

        print("=" * 60)

        return False


# =========================================================
# SEND TEXT
# =========================================================

def send_message(text):

    return telegram_call(
        "sendMessage",
        chat_id=CHAT_ID,
        text=text[:4096],
        disable_web_page_preview=False
    )


# =========================================================
# SEND PHOTO
# =========================================================

def send_photo(photo_url, caption=""):

    return telegram_call(
        "sendPhoto",
        chat_id=CHAT_ID,
        photo=photo_url,
        caption=caption[:1024]
    )


# =========================================================
# SEND VIDEO
# =========================================================

def send_video(video_url, caption=""):

    return telegram_call(
        "sendVideo",
        chat_id=CHAT_ID,
        video=video_url,
        caption=caption[:1024],
        supports_streaming=True
    )


# =========================================================
# DOWNLOAD MEDIA
# =========================================================

def download_file(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=120
    )

    response.raise_for_status()

    filename = (
        url.split("?")[0]
        .rstrip("/")
        .split("/")[-1]
    )

    if not filename:

        filename = "telegram_media"

    path = f"/tmp/{filename}"

    with open(path, "wb") as f:

        f.write(response.content)

    return path


# =========================================================
# SEND LOCAL FILE
# =========================================================

def send_document_file(
    file_path,
    caption=""
):

    with open(
        file_path,
        "rb"
    ) as file:

        response = requests.post(
            f"{API}/sendDocument",
            data={
                "chat_id": CHAT_ID,
                "caption": caption[:1024]
            },
            files={
                "document": file
            },
            timeout=180
        )

    try:

        result = response.json()

    except Exception:

        raise Exception(
            f"Telegram HTTP "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    if not result.get("ok"):

        raise Exception(
            f"Telegram API error "
            f"{result.get('error_code')}: "
            f"{result.get('description')}"
        )

    return result


# =========================================================
# FETCH CHANNEL
# =========================================================

def fetch_channel_posts(username):

    username = (
        username
        .strip()
        .lstrip("@")
    )

    url = f"https://t.me/s/{username}"

    print(
        f"[FETCH] {url}"
    )

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

        data_post = wrap.get(
            "data-post"
        )

        if not data_post:
            continue

        try:

            channel_name, post_id_text = (
                data_post.rsplit("/", 1)
            )

            post_id = int(
                post_id_text
            )

        except Exception:

            continue

        # -------------------------
        # TEXT
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
        # LINK
        # -------------------------

        link = (
            f"https://t.me/"
            f"{channel_name}/"
            f"{post_id}"
        )

        # -------------------------
        # PHOTO
        # -------------------------

        photos = []

        for photo in wrap.select(
            "a.tgme_widget_message_photo_wrap"
        ):

            style = photo.get(
                "style",
                ""
            )

            match = re.search(
                r"url\(['\"]?([^'\")]+)",
                style
            )

            if match:

                photos.append(
                    match.group(1)
                )

        # -------------------------
        # VIDEO
        # -------------------------

        video_url = None

        video = wrap.select_one(
            "video"
        )

        if video:

            source = video.select_one(
                "source"
            )

            if source:

                video_url = source.get(
                    "src"
                )

            if not video_url:

                video_url = video.get(
                    "src"
                )

        posts.append(
            {
                "id": post_id,
                "text": text,
                "link": link,
                "photos": photos,
                "video": video_url
            }
        )

    posts.sort(
        key=lambda x: x["id"]
    )

    return posts


# =========================================================
# SEND POST
# =========================================================

def send_post(
    post,
    username
):

    post_id = post["id"]

    text = (
        post.get("text")
        or ""
    ).strip()

    link = post["link"]

    photos = post.get(
        "photos",
        []
    )

    video = post.get(
        "video"
    )

    print(
        f"[SEND] @{username} "
        f"post={post_id} "
        f"photos={len(photos)} "
        f"video={bool(video)}"
    )

    caption = (
        f"📢 @{username}\n\n"
        f"{text}\n\n"
        f"🔗 {link}"
    )

    # =====================================================
    # TEXT ONLY
    # =====================================================

    if not photos and not video:

        try:

            send_message(
                caption
            )

            print(
                f"[OK] متن پست {post_id} ارسال شد."
            )

            return True

        except Exception as e:

            print(
                f"[ERROR] ارسال متن "
                f"پست {post_id}: {e}"
            )

            return False

    # =====================================================
    # PHOTO
    # =====================================================

    if photos:

        success = False

        for index, photo_url in enumerate(
            photos
        ):

            photo_caption = (
                caption
                if index == 0
                else ""
            )

            try:

                print(
                    f"[PHOTO] "
                    f"{index + 1}/{len(photos)}"
                )

                send_photo(
                    photo_url,
                    photo_caption
                )

                success = True

                print(
                    "[OK] عکس ارسال شد."
                )

            except Exception as e:

                print(
                    f"[WARN] ارسال مستقیم عکس "
                    f"ناموفق بود: {e}"
                )

                # تلاش دوم: دانلود و آپلود
                try:

                    local_file = download_file(
                        photo_url
                    )

                    send_document_file(
                        local_file,
                        photo_caption
                    )

                    try:
                        os.remove(
                            local_file
                        )
                    except Exception:
                        pass

                    success = True

                    print(
                        "[OK] عکس با آپلود مستقیم "
                        "ارسال شد."
                    )

                except Exception as e2:

                    print(
                        f"[ERROR] تلاش دوم عکس "
                        f"ناموفق بود: {e2}"
                    )

        return success

    # =====================================================
    # VIDEO
    # =====================================================

    if video:

        try:

            send_video(
                video,
                caption
            )

            print(
                "[OK] ویدیو ارسال شد."
            )

            return True

        except Exception as e:

            print(
                f"[WARN] ارسال ویدیو ناموفق بود: {e}"
            )

            # اگر ویدیو بزرگ باشد Telegram
            # ممکن است 413 بدهد.
            # در این حالت حداقل لینک را ارسال می‌کنیم.

            try:

                send_message(
                    f"🎬 پست جدید از @{username}\n\n"
                    f"{text}\n\n"
                    f"🔗 {link}\n\n"
                    f"⚠️ ارسال مستقیم ویدیو "
                    f"به دلیل محدودیت حجم ناموفق بود."
                )

                print(
                    "[OK] لینک ویدیو ارسال شد."
                )

                return True

            except Exception as e2:

                print(
                    f"[ERROR] ارسال لینک هم شکست خورد: {e2}"
                )

                return False

    return False


# =========================================================
# COMMANDS
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

        result = telegram_call(
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
            f"[WARN] getUpdates: {e}"
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

        user_id = (
            message
            .get("from", {})
            .get("id")
        )

        chat_id = (
            message
            .get("chat", {})
            .get("id")
        )

        text = (
            message.get("text")
            or ""
        ).strip()

        if not text:
            continue

        # فقط مالک
        if user_id != OWNER_ID:
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

        # -----------------------------------------
        # /id
        # -----------------------------------------

        if command == "/id":

            send_message_to_chat(
                chat_id,
                f"🆔 Chat ID:\n{chat_id}"
            )

        # -----------------------------------------
        # HELP
        # -----------------------------------------

        elif command in (
            "/start",
            "/help",
            "/manage"
        ):

            send_message_to_chat(
                chat_id,
                HELP_TEXT
            )

        # -----------------------------------------
        # ADD
        # -----------------------------------------

        elif command == "/add":

            username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            if not username:

                send_message_to_chat(
                    chat_id,
                    "مثال:\n/add akhbarfars"
                )

                continue

            if username in [
                c.lower().lstrip("@")
                for c in channels
            ]:

                send_message_to_chat(
                    chat_id,
                    f"⚠️ @{username} قبلاً اضافه شده."
                )

                continue

            channels.append(
                username
            )

            send_message_to_chat(
                chat_id,
                f"✅ @{username} اضافه شد."
            )

        # -----------------------------------------
        # REMOVE
        # -----------------------------------------

        elif command == "/remove":

            username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            old_length = len(
                channels
            )

            channels = [
                c for c in channels
                if c.lower().lstrip("@")
                != username
            ]

            if len(channels) < old_length:

                send_message_to_chat(
                    chat_id,
                    f"🗑 @{username} حذف شد."
                )

            else:

                send_message_to_chat(
                    chat_id,
                    f"❌ @{username} پیدا نشد."
                )

        # -----------------------------------------
        # LIST
        # -----------------------------------------

        elif command == "/list":

            if not channels:

                send_message_to_chat(
                    chat_id,
                    "📋 لیست کانال‌ها خالی است."
                )

            else:

                send_message_to_chat(
                    chat_id,
                    "📋 کانال‌های فعال:\n\n"
                    + "\n".join(
                        f"• @{c}"
                        for c in channels
                    )
                )

        else:

            send_message_to_chat(
                chat_id,
                "❌ دستور ناشناخته است.\n\n"
                + HELP_TEXT
            )

    return channels, bot_state


# =========================================================
# SEND MESSAGE TO ANY CHAT
# =========================================================

def send_message_to_chat(
    chat_id,
    text
):

    return telegram_call(
        "sendMessage",
        chat_id=chat_id,
        text=text[:4096]
    )


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

        print("")
        print(
            f"[CHECK] @{username}"
        )

        try:

            posts = fetch_channel_posts(
                username
            )

        except Exception as e:

            print(
                f"[ERROR] دریافت @{username}: {e}"
            )

            continue

        print(
            f"[FOUND] {len(posts)} پست در صفحه"
        )

        if not posts:

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
        # NEW
        # =================================================

        new_posts = [
            p for p in posts
            if p["id"] > last_id
        ]

        if not new_posts:

            print(
                f"[INFO] پست جدیدی نیست."
            )

            continue

        print(
            f"[NEW] {len(new_posts)} پست جدید"
        )

        all_success = True

        for post in new_posts:

            success = send_post(
                post,
                username
            )

            if success:

                print(
                    f"[SUCCESS] @{username} "
                    f"post={post['id']}"
                )

            else:

                print(
                    f"[FAILED] @{username} "
                    f"post={post['id']}"
                )

                all_success = False

                # اگر یک پست شکست خورد،
                # state جلو نمی‌رود.
                break

            time.sleep(2)

        # فقط در صورت موفقیت کامل
        # state را جلو می‌بریم.
        if all_success:

            state[
                username
            ] = max(
                p["id"]
                for p in new_posts
            )

            print(
                f"[STATE] @{username} "
                f"updated to {state[username]}"
            )

        else:

            print(
                f"[STATE] @{username} "
                f"NOT updated بسبب ارسال ناموفق"
            )

    return state


# =========================================================
# MAIN
# =========================================================

def main():

    print("")
    print("=" * 60)
    print("TELEGRAM PUBLIC CHANNEL FORWARDER")
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

    # =====================================================
    # TEST DESTINATION
    # =====================================================

    if not test_destination():

        print(
            "[STOP] مقصد معتبر نیست."
        )

        return

    # =====================================================
    # COMMANDS
    # =====================================================

    channels, bot_state = handle_updates(
        channels,
        bot_state
    )

    # =====================================================
    # CHANNELS
    # =====================================================

    state = check_channels(
        channels,
        state
    )

    # =====================================================
    # SAVE
    # =====================================================

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

    print("")
    print("=" * 60)
    print("[DONE] اجرای برنامه تمام شد.")
    print("=" * 60)


if __name__ == "__main__":
    main()
