import os
import json
import time
import re
import tempfile
import mimetypes
import requests

from bs4 import BeautifulSoup
from urllib.parse import urlparse


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
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

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            f"[ERROR] خواندن {path}: {e}"
        )

        return default


def save_json(path, data):

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

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
            f"{result.get('error_code', response.status_code)}: "
            f"{result.get('description', 'Unknown error')}"
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
        f"[INFO] DESTINATION_ID = {CHAT_ID}"
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
# MEDIA URL CLEANUP
# =========================================================

def clean_media_url(url):

    if not url:
        return None

    url = url.strip()

    # حذف کوتیشن‌های احتمالی
    url = url.strip("\"'")

    # تبدیل HTML entities احتمالی
    url = (
        url.replace("&amp;", "&")
           .replace("&quot;", "\"")
           .replace("&#39;", "'")
    )

    return url


# =========================================================
# DOWNLOAD MEDIA
# =========================================================

def download_media(url):

    url = clean_media_url(url)

    if not url:
        raise Exception("Media URL خالی است.")

    print(
        f"[DOWNLOAD] {url[:250]}"
    )

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=180,
            stream=True
        )

        response.raise_for_status()

    except requests.RequestException as e:

        raise Exception(
            f"دانلود مدیا ناموفق بود: {e}"
        )

    # -----------------------------------------------------
    # Content-Type
    # -----------------------------------------------------

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
        .split(";")[0]
        .strip()
    )

    # -----------------------------------------------------
    # Extension
    # -----------------------------------------------------

    extension = ""

    guessed = mimetypes.guess_extension(
        content_type
    )

    if guessed:
        extension = guessed

    # اگر از Content-Type تشخیص داده نشد
    if not extension:

        path = urlparse(url).path

        match = re.search(
            r"(\.(jpg|jpeg|png|webp|gif|mp4|mov|m4v|webm))$",
            path,
            re.IGNORECASE
        )

        if match:

            extension = (
                "." +
                match.group(1)
                .lstrip(".")
                .lower()
            )

    # -----------------------------------------------------
    # Fallback
    # -----------------------------------------------------

    if not extension:

        extension = ".bin"

    # -----------------------------------------------------
    # Safe short filename
    #
    # بسیار مهم:
    # دیگر URL را اسم فایل نمی‌کنیم.
    # -----------------------------------------------------

    suffix = extension[:10]

    temp = tempfile.NamedTemporaryFile(
        prefix="tg_media_",
        suffix=suffix,
        delete=False
    )

    file_path = temp.name

    total_size = 0

    try:

        with temp:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if not chunk:
                    continue

                temp.write(chunk)

                total_size += len(chunk)

        print(
            f"[DOWNLOAD OK] "
            f"{total_size / 1024 / 1024:.2f} MB "
            f"-> {file_path}"
        )

        if total_size == 0:

            raise Exception(
                "فایل دانلود شد ولی حجم آن صفر است."
            )

        return file_path, content_type, total_size

    except Exception:

        try:
            os.remove(file_path)
        except Exception:
            pass

        raise


# =========================================================
# REMOVE TEMP FILE
# =========================================================

def remove_temp_file(path):

    if not path:
        return

    try:

        if os.path.exists(path):

            os.remove(path)

    except Exception:

        pass


# =========================================================
# SEND PHOTO BY URL
# =========================================================

def send_photo_url(
    photo_url,
    caption=""
):

    return telegram_call(
        "sendPhoto",
        chat_id=CHAT_ID,
        photo=photo_url,
        caption=caption[:1024]
    )


# =========================================================
# SEND PHOTO BY LOCAL FILE
# =========================================================

def send_photo_file(
    file_path,
    caption=""
):

    print(
        f"[UPLOAD PHOTO] {file_path}"
    )

    with open(
        file_path,
        "rb"
    ) as file:

        response = requests.post(
            f"{API}/sendPhoto",
            data={
                "chat_id": CHAT_ID,
                "caption": caption[:1024]
            },
            files={
                "photo": file
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
# SEND VIDEO BY URL
# =========================================================

def send_video_url(
    video_url,
    caption=""
):

    return telegram_call(
        "sendVideo",
        chat_id=CHAT_ID,
        video=video_url,
        caption=caption[:1024],
        supports_streaming=True
    )


# =========================================================
# SEND VIDEO BY LOCAL FILE
# =========================================================

def send_video_file(
    file_path,
    caption=""
):

    print(
        f"[UPLOAD VIDEO] {file_path}"
    )

    with open(
        file_path,
        "rb"
    ) as file:

        response = requests.post(
            f"{API}/sendVideo",
            data={
                "chat_id": CHAT_ID,
                "caption": caption[:1024],
                "supports_streaming": "true"
            },
            files={
                "video": file
            },
            timeout=300
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
# FETCH CHANNEL POSTS
# =========================================================

def fetch_channel_posts(username):

    username = (
        username
        .strip()
        .lstrip("@")
    )

    url = (
        f"https://t.me/s/{username}"
    )

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

        # -------------------------------------------------
        # TEXT
        # -------------------------------------------------

        text_div = wrap.select_one(
            ".tgme_widget_message_text"
        )

        text = ""

        if text_div:

            text = text_div.get_text(
                "\n",
                strip=True
            )

        # -------------------------------------------------
        # LINK
        # -------------------------------------------------

        link = (
            f"https://t.me/"
            f"{channel_name}/"
            f"{post_id}"
        )

        # -------------------------------------------------
        # PHOTOS
        # -------------------------------------------------

        photos = []

        for photo in wrap.select(
            "a.tgme_widget_message_photo_wrap"
        ):

            style = photo.get(
                "style",
                ""
            )

            # حالت عادی
            match = re.search(
                r"url\(['\"]?([^'\")]+)",
                style
            )

            if match:

                media_url = clean_media_url(
                    match.group(1)
                )

                if media_url:

                    photos.append(
                        media_url
                    )

        # حذف موارد تکراری
        photos = list(
            dict.fromkeys(photos)
        )

        # -------------------------------------------------
        # VIDEO
        # -------------------------------------------------

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

            video_url = clean_media_url(
                video_url
            )

        # -------------------------------------------------
        # SAVE
        # -------------------------------------------------

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
# SEND TEXT FALLBACK
# =========================================================

def send_media_fallback_message(
    username,
    text,
    link,
    media_type
):

    if media_type == "video":

        prefix = "🎬"

    else:

        prefix = "🖼"

    message = (
        f"{prefix} پست جدید از @{username}\n\n"
        f"{text}\n\n"
        f"🔗 {link}\n\n"
        f"⚠️ ارسال فایل مدیا ناموفق بود."
    )

    send_message(
        message
    )


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
                f"[OK] متن پست "
                f"{post_id} ارسال شد."
            )

            return True

        except Exception as e:

            print(
                f"[ERROR] ارسال متن "
                f"پست {post_id}: {e}"
            )

            return False

    # =====================================================
    # VIDEO
    # =====================================================

    if video:

        temp_file = None

        # -----------------------------------------------
        # تلاش اول:
        # ارسال مستقیم URL
        # -----------------------------------------------

        try:

            print(
                "[VIDEO] تلاش ارسال مستقیم..."
            )

            send_video_url(
                video,
                caption
            )

            print(
                f"[OK] ویدیو پست "
                f"{post_id} ارسال شد."
            )

            return True

        except Exception as e:

            print(
                f"[WARN] ارسال مستقیم ویدیو "
                f"ناموفق بود: {e}"
            )

        # -----------------------------------------------
        # تلاش دوم:
        # دانلود و آپلود فایل
        # -----------------------------------------------

        try:

            print(
                "[VIDEO] دانلود و آپلود فایل..."
            )

            temp_file, content_type, size = (
                download_media(video)
            )

            # Telegram Bot API محدودیت حجم دارد.
            # اگر فایل خیلی بزرگ بود، حداقل لینک را می‌فرستیم.

            if size > 49 * 1024 * 1024:

                print(
                    f"[WARN] ویدیو بزرگ است: "
                    f"{size / 1024 / 1024:.2f} MB"
                )

                remove_temp_file(
                    temp_file
                )

                send_media_fallback_message(
                    username,
                    text,
                    link,
                    "video"
                )

                return True

            send_video_file(
                temp_file,
                caption
            )

            print(
                f"[OK] ویدیو پست "
                f"{post_id} با آپلود فایل ارسال شد."
            )

            remove_temp_file(
                temp_file
            )

            return True

        except Exception as e:

            print(
                f"[ERROR] آپلود ویدیو "
                f"ناموفق بود: {e}"
            )

            remove_temp_file(
                temp_file
            )

            try:

                send_media_fallback_message(
                    username,
                    text,
                    link,
                    "video"
                )

                print(
                    "[OK] لینک ویدیو ارسال شد."
                )

                return True

            except Exception as e2:

                print(
                    f"[ERROR] ارسال fallback "
                    f"ناموفق بود: {e2}"
                )

                return False

    # =====================================================
    # PHOTO
    # =====================================================

    if photos:

        success = True

        for index, photo_url in enumerate(
            photos
        ):

            photo_caption = (
                caption
                if index == 0
                else ""
            )

            temp_file = None

            print(
                f"[PHOTO] "
                f"{index + 1}/{len(photos)}"
            )

            # -------------------------------------------
            # تلاش اول:
            # ارسال مستقیم URL
            # -------------------------------------------

            try:

                print(
                    "[PHOTO] تلاش ارسال مستقیم..."
                )

                send_photo_url(
                    photo_url,
                    photo_caption
                )

                print(
                    "[OK] عکس با URL ارسال شد."
                )

                continue

            except Exception as e:

                print(
                    f"[WARN] ارسال مستقیم عکس "
                    f"ناموفق بود: {e}"
                )

            # -------------------------------------------
            # تلاش دوم:
            # دانلود و آپلود فایل
            # -------------------------------------------

            try:

                print(
                    "[PHOTO] دانلود عکس..."
                )

                temp_file, content_type, size = (
                    download_media(photo_url)
                )

                # محدودیت تقریبی Telegram
                if size > 9 * 1024 * 1024:

                    print(
                        f"[WARN] عکس بزرگ است: "
                        f"{size / 1024 / 1024:.2f} MB"
                    )

                    # اگر خیلی بزرگ بود، به صورت document
                    # تلاش می‌کنیم.

                    with open(
                        temp_file,
                        "rb"
                    ) as file:

                        response = requests.post(
                            f"{API}/sendDocument",
                            data={
                                "chat_id": CHAT_ID,
                                "caption": photo_caption[:1024]
                            },
                            files={
                                "document": file
                            },
                            timeout=180
                        )

                    result = response.json()

                    if not result.get("ok"):

                        raise Exception(
                            f"Telegram API error "
                            f"{result.get('error_code')}: "
                            f"{result.get('description')}"
                        )

                else:

                    send_photo_file(
                        temp_file,
                        photo_caption
                    )

                print(
                    "[OK] عکس با آپلود فایل ارسال شد."
                )

            except Exception as e:

                print(
                    f"[ERROR] ارسال عکس "
                    f"{index + 1} ناموفق بود: {e}"
                )

                success = False

            finally:

                remove_temp_file(
                    temp_file
                )

        return success

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

    print(
        f"[INFO] تعداد Update دریافت‌شده: "
        f"{len(updates)}"
    )

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

        # فقط OWNER
        if user_id != OWNER_ID:
            continue

        parts = text.split(
            maxsplit=1
        )

        command = (
            parts[0]
            .lower()
            .split("@")[0]
        )

        argument = (
            parts[1].strip()
            if len(parts) > 1
            else ""
        )

        # -----------------------------------------
        # ID
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

            existing = [
                c.lower().lstrip("@")
                for c in channels
            ]

            if username in existing:

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
                c
                for c in channels
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
                    +
                    "\n".join(
                        f"• @{c}"
                        for c in channels
                    )
                )

        # -----------------------------------------
        # UNKNOWN
        # -----------------------------------------

        else:

            send_message_to_chat(
                chat_id,
                "❌ دستور ناشناخته است.\n\n"
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

        print("")
        print(
            f"[CHECK] @{username}"
        )

        # -------------------------------------------------
        # FETCH
        # -------------------------------------------------

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

        # -------------------------------------------------
        # LAST STATE
        # -------------------------------------------------

        last_id = state.get(
            username
        )

        # -------------------------------------------------
        # FIRST RUN
        # -------------------------------------------------

        if last_id is None:

            state[
                username
            ] = posts[-1]["id"]

            print(
                f"[INIT] @{username} "
                f"baseline={posts[-1]['id']}"
            )

            continue

        # -------------------------------------------------
        # NEW POSTS
        # -------------------------------------------------

        new_posts = [
            p
            for p in posts
            if p["id"] > last_id
        ]

        if not new_posts:

            print(
                "[INFO] پست جدیدی نیست."
            )

            continue

        print(
            f"[NEW] {len(new_posts)} پست جدید"
        )

        all_success = True

        # -------------------------------------------------
        # SEND
        # -------------------------------------------------

        for post in new_posts:

            try:

                success = send_post(
                    post,
                    username
                )

            except Exception as e:

                print(
                    f"[ERROR] خطای کلی ارسال "
                    f"post={post['id']}: {e}"
                )

                success = False

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

                # state جلو نمی‌رود
                break

            time.sleep(2)

        # -------------------------------------------------
        # UPDATE STATE
        # -------------------------------------------------

        if all_success:

            state[
                username
            ] = max(
                p["id"]
                for p in new_posts
            )

            print(
                f"[STATE] @{username} "
                f"updated to "
                f"{state[username]}"
            )

        else:

            print(
                f"[STATE] @{username} "
                f"NOT updated because "
                f"sending failed."
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

    # -----------------------------------------------------
    # LOAD
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # TEST DESTINATION
    # -----------------------------------------------------

    if not test_destination():

        print(
            "[STOP] مقصد معتبر نیست."
        )

        return

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    channels, bot_state = handle_updates(
        channels,
        bot_state
    )

    # -----------------------------------------------------
    # CHECK CHANNELS
    # -----------------------------------------------------

    state = check_channels(
        channels,
        state
    )

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

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


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
