import os
import json
import time
import re
import requests
from bs4 import BeautifulSoup


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()

# CHAT_ID دیگر اجباری نیست.
# اگر اشتباه باشد، می‌توانیم از /setdestination استفاده کنیم.
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

OWNER_ID = int(
    os.environ["OWNER_ID"].strip()
)

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
    "/setdestination - تعیین همین چت به عنوان مقصد\n"
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
# DESTINATION
# =========================================================

def get_destination_id(bot_state):

    # اولویت با مقصدی است که با /setdestination ذخیره شده
    saved_destination = (
        bot_state.get(
            "destination_chat_id"
        )
    )

    if saved_destination:

        return str(saved_destination).strip()

    # در غیر این صورت از GitHub Secret استفاده می‌کنیم
    if CHAT_ID:

        return CHAT_ID

    return ""


def test_destination(bot_state):

    destination_id = get_destination_id(
        bot_state
    )

    print("")
    print("=" * 60)
    print("TESTING DESTINATION CHAT")
    print("=" * 60)

    if not destination_id:

        print(
            "[ERROR] هیچ مقصدی تنظیم نشده."
        )

        print("")
        print(
            "داخل گروه مقصد دستور زیر را بفرست:"
        )

        print(
            "/setdestination"
        )

        print("=" * 60)

        return False

    print(
        f"[INFO] DESTINATION_ID = "
        f"{destination_id}"
    )

    try:

        result = telegram_call(
            "getChat",
            chat_id=destination_id
        )

        chat = result.get(
            "result",
            {}
        )

        print("")
        print("[OK] مقصد پیدا شد.")

        print(
            f"[CHAT ID] "
            f"{chat.get('id')}"
        )

        print(
            f"[CHAT TYPE] "
            f"{chat.get('type')}"
        )

        print(
            f"[CHAT TITLE] "
            f"{chat.get('title')}"
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
        print(
            "[ERROR] مقصد Telegram معتبر نیست."
        )

        print(
            f"[DETAIL] {e}"
        )

        print("")
        print(
            "اگر CHAT_ID اشتباه است، "
            "داخل گروه مقصد /setdestination "
            "را بفرست."
        )

        print("=" * 60)

        return False


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
        text=text[:4096],
        disable_web_page_preview=False
    )


# =========================================================
# SEND MESSAGE TO DESTINATION
# =========================================================

def send_message(text, bot_state):

    destination_id = get_destination_id(
        bot_state
    )

    if not destination_id:

        raise Exception(
            "Destination chat ID is not configured."
        )

    return telegram_call(
        "sendMessage",
        chat_id=destination_id,
        text=text[:4096],
        disable_web_page_preview=False
    )


# =========================================================
# SEND PHOTO
# =========================================================

def send_photo(
    photo_url,
    caption,
    bot_state
):

    destination_id = get_destination_id(
        bot_state
    )

    if not destination_id:

        raise Exception(
            "Destination chat ID is not configured."
        )

    return telegram_call(
        "sendPhoto",
        chat_id=destination_id,
        photo=photo_url,
        caption=caption[:1024]
    )


# =========================================================
# SEND VIDEO
# =========================================================

def send_video(
    video_url,
    caption,
    bot_state
):

    destination_id = get_destination_id(
        bot_state
    )

    if not destination_id:

        raise Exception(
            "Destination chat ID is not configured."
        )

    return telegram_call(
        "sendVideo",
        chat_id=destination_id,
        video=video_url,
        caption=caption[:1024],
        supports_streaming=True
    )


# =========================================================
# DOWNLOAD MEDIA
# =========================================================

def download_file(url):

    print(
        f"[DOWNLOAD] {url}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=180
    )

    response.raise_for_status()

    filename = (
        url.split("?")[0]
        .rstrip("/")
        .split("/")[-1]
    )

    if not filename:

        filename = "telegram_media"

    # حذف کاراکترهای خطرناک از اسم فایل
    filename = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        filename
    )

    path = (
        f"/tmp/{filename}"
    )

    with open(
        path,
        "wb"
    ) as f:

        f.write(
            response.content
        )

    return path


# =========================================================
# SEND LOCAL DOCUMENT
# =========================================================

def send_document_file(
    file_path,
    caption,
    bot_state
):

    destination_id = get_destination_id(
        bot_state
    )

    if not destination_id:

        raise Exception(
            "Destination chat ID is not configured."
        )

    with open(
        file_path,
        "rb"
    ) as file:

        response = requests.post(
            f"{API}/sendDocument",
            data={
                "chat_id": destination_id,
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
# SEND LOCAL PHOTO
# =========================================================

def send_photo_file(
    file_path,
    caption,
    bot_state
):

    destination_id = get_destination_id(
        bot_state
    )

    if not destination_id:

        raise Exception(
            "Destination chat ID is not configured."
        )

    with open(
        file_path,
        "rb"
    ) as file:

        response = requests.post(
            f"{API}/sendPhoto",
            data={
                "chat_id": destination_id,
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

        # =================================================
        # TEXT
        # =================================================

        text_div = wrap.select_one(
            ".tgme_widget_message_text"
        )

        text = ""

        if text_div:

            text = text_div.get_text(
                "\n",
                strip=True
            )

        # =================================================
        # LINK
        # =================================================

        link = (
            f"https://t.me/"
            f"{channel_name}/"
            f"{post_id}"
        )

        # =================================================
        # PHOTO
        # =================================================

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

        # =================================================
        # VIDEO
        # =================================================

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
    username,
    bot_state
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

    # اگر متن خالی بود
    if not text:

        text = "پست جدید"

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
                caption,
                bot_state
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
    # PHOTO
    # =====================================================

    if photos:

        success_count = 0

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
                    photo_caption,
                    bot_state
                )

                success_count += 1

                print(
                    "[OK] عکس مستقیم ارسال شد."
                )

            except Exception as e:

                print(
                    "[WARN] ارسال مستقیم عکس "
                    f"ناموفق بود: {e}"
                )

                # -----------------------------------------
                # DOWNLOAD + UPLOAD PHOTO
                # -----------------------------------------

                try:

                    local_file = download_file(
                        photo_url
                    )

                    try:

                        send_photo_file(
                            local_file,
                            photo_caption,
                            bot_state
                        )

                        success_count += 1

                        print(
                            "[OK] عکس با آپلود مستقیم "
                            "ارسال شد."
                        )

                    finally:

                        try:

                            os.remove(
                                local_file
                            )

                        except Exception:
                            pass

                except Exception as e2:

                    print(
                        "[ERROR] آپلود عکس شکست خورد: "
                        f"{e2}"
                    )

        return success_count == len(
            photos
        )

    # =====================================================
    # VIDEO
    # =====================================================

    if video:

        try:

            send_video(
                video,
                caption,
                bot_state
            )

            print(
                "[OK] ویدیو ارسال شد."
            )

            return True

        except Exception as e:

            print(
                "[WARN] ارسال مستقیم ویدیو "
                f"ناموفق بود: {e}"
            )

            # -----------------------------------------
            # DOWNLOAD + UPLOAD VIDEO
            # -----------------------------------------

            try:

                local_file = download_file(
                    video
                )

                try:

                    # ابتدا تلاش می‌کنیم فایل را
                    # به عنوان document بفرستیم.
                    send_document_file(
                        local_file,
                        caption,
                        bot_state
                    )

                    print(
                        "[OK] ویدیو به صورت فایل "
                        "ارسال شد."
                    )

                    return True

                finally:

                    try:

                        os.remove(
                            local_file
                        )

                    except Exception:
                        pass

            except Exception as e2:

                print(
                    "[WARN] آپلود ویدیو هم شکست خورد: "
                    f"{e2}"
                )

            # -----------------------------------------
            # FALLBACK LINK
            # -----------------------------------------

            try:

                send_message(
                    f"🎬 پست جدید از @{username}\n\n"
                    f"{text}\n\n"
                    f"🔗 {link}\n\n"
                    f"⚠️ ارسال فایل ویدیو "
                    f"به دلیل محدودیت Telegram "
                    f"ناموفق بود.",
                    bot_state
                )

                print(
                    "[OK] لینک ویدیو ارسال شد."
                )

                return True

            except Exception as e3:

                print(
                    "[ERROR] ارسال لینک ویدیو "
                    f"هم شکست خورد: {e3}"
                )

                return False

    return False


# =========================================================
# COMMANDS / UPDATES
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

        chat = message.get(
            "chat",
            {}
        )

        chat_id = chat.get(
            "id"
        )

        chat_type = chat.get(
            "type"
        )

        chat_title = chat.get(
            "title",
            ""
        )

        user = message.get(
            "from",
            {}
        )

        user_id = user.get(
            "id"
        )

        text = (
            message.get("text")
            or ""
        ).strip()

        # =================================================
        # DEBUG CHAT
        # =================================================

        print(
            f"[UPDATE] "
            f"chat_id={chat_id} "
            f"type={chat_type} "
            f"title={chat_title} "
            f"user_id={user_id}"
        )

        # =================================================
        # فقط OWNER
        # =================================================

        if user_id != OWNER_ID:

            continue

        if not text:

            continue

        parts = text.split(
            maxsplit=1
        )

        command = (
            parts[0]
            .split("@")[0]
            .lower()
        )

        argument = (
            parts[1].strip()
            if len(parts) > 1
            else ""
        )

        # =================================================
        # /id
        # =================================================

        if command == "/id":

            response_text = (
                "🆔 اطلاعات چت\n\n"
                f"Chat ID: `{chat_id}`\n"
                f"Type: {chat_type}\n"
                f"Title: {chat_title or '-'}"
            )

            # چون parse_mode استفاده نکرده‌ایم،
            # بک‌تیک را حذف می‌کنیم.
            response_text = (
                "🆔 اطلاعات چت\n\n"
                f"Chat ID: {chat_id}\n"
                f"Type: {chat_type}\n"
                f"Title: {chat_title or '-'}"
            )

            try:

                send_message_to_chat(
                    chat_id,
                    response_text
                )

            except Exception as e:

                print(
                    f"[ERROR] ارسال /id: {e}"
                )

            continue

        # =================================================
        # /setdestination
        # =================================================

        if command == "/setdestination":

            # فقط گروه یا سوپرگروه
            if chat_type not in (
                "group",
                "supergroup"
            ):

                try:

                    send_message_to_chat(
                        chat_id,
                        "❌ این دستور را داخل "
                        "گروه مقصد اجرا کن."
                    )

                except Exception as e:

                    print(
                        f"[ERROR] {e}"
                    )

                continue

            # ذخیره مقصد
            bot_state[
                "destination_chat_id"
            ] = str(chat_id)

            bot_state[
                "destination_chat_type"
            ] = chat_type

            bot_state[
                "destination_chat_title"
            ] = chat_title

            try:

                send_message_to_chat(
                    chat_id,
                    "✅ این گروه به عنوان مقصد "
                    "ارسال پست ذخیره شد.\n\n"
                    f"🆔 Chat ID: {chat_id}\n"
                    f"📌 نام: {chat_title or '-'}"
                )

            except Exception as e:

                print(
                    f"[ERROR] پاسخ /setdestination: {e}"
                )

            print("")
            print(
                "=" * 60
            )
            print(
                "[DESTINATION SET]"
            )
            print(
                f"ID: {chat_id}"
            )
            print(
                f"TYPE: {chat_type}"
            )
            print(
                f"TITLE: {chat_title}"
            )
            print(
                "=" * 60
            )

            continue

        # =================================================
        # HELP
        # =================================================

        if command in (
            "/start",
            "/help",
            "/manage"
        ):

            try:

                send_message_to_chat(
                    chat_id,
                    HELP_TEXT
                )

            except Exception as e:

                print(
                    f"[ERROR] ارسال help: {e}"
                )

            continue

        # =================================================
        # ADD
        # =================================================

        if command == "/add":

            username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            if not username:

                try:

                    send_message_to_chat(
                        chat_id,
                        "مثال:\n"
                        "/add akhbarfars"
                    )

                except Exception as e:

                    print(
                        f"[ERROR] {e}"
                    )

                continue

            normalized_channels = [
                c.lower().lstrip("@")
                for c in channels
            ]

            if username in normalized_channels:

                try:

                    send_message_to_chat(
                        chat_id,
                        f"⚠️ @{username} "
                        "قبلاً اضافه شده."
                    )

                except Exception as e:

                    print(
                        f"[ERROR] {e}"
                    )

                continue

            channels.append(
                username
            )

            try:

                send_message_to_chat(
                    chat_id,
                    f"✅ @{username} اضافه شد."
                )

            except Exception as e:

                print(
                    f"[ERROR] {e}"
                )

            continue

        # =================================================
        # REMOVE
        # =================================================

        if command == "/remove":

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

                response = (
                    f"🗑 @{username} حذف شد."
                )

            else:

                response = (
                    f"❌ @{username} پیدا نشد."
                )

            try:

                send_message_to_chat(
                    chat_id,
                    response
                )

            except Exception as e:

                print(
                    f"[ERROR] {e}"
                )

            continue

        # =================================================
        # LIST
        # =================================================

        if command == "/list":

            if not channels:

                response = (
                    "📋 لیست کانال‌ها خالی است."
                )

            else:

                response = (
                    "📋 کانال‌های فعال:\n\n"
                    +
                    "\n".join(
                        f"• @{c}"
                        for c in channels
                    )
                )

            try:

                send_message_to_chat(
                    chat_id,
                    response
                )

            except Exception as e:

                print(
                    f"[ERROR] {e}"
                )

            continue

        # =================================================
        # UNKNOWN
        # =================================================

        try:

            send_message_to_chat(
                chat_id,
                "❌ دستور ناشناخته است.\n\n"
                + HELP_TEXT
            )

        except Exception as e:

            print(
                f"[ERROR] {e}"
            )

    return channels, bot_state


# =========================================================
# CHECK CHANNELS
# =========================================================

def check_channels(
    channels,
    state,
    bot_state
):

    for username in channels:

        username = (
            username
            .strip()
            .lstrip("@")
        )

        if not username:

            continue

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
                f"[ERROR] دریافت "
                f"@{username}: {e}"
            )

            continue

        print(
            f"[FOUND] {len(posts)} پست "
            "در صفحه"
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
        # NEW POSTS
        # =================================================

        new_posts = [
            p for p in posts
            if p["id"] > last_id
        ]

        if not new_posts:

            print(
                "[INFO] پست جدیدی نیست."
            )

            continue

        print(
            f"[NEW] {len(new_posts)} "
            "پست جدید"
        )

        all_success = True

        for post in new_posts:

            success = send_post(
                post,
                username,
                bot_state
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

                break

            time.sleep(2)

        # =================================================
        # UPDATE STATE
        # =================================================

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
                "NOT updated because "
                "sending failed."
            )

    return state


# =========================================================
# MAIN
# =========================================================

def main():

    print("")
    print("=" * 60)
    print(
        "TELEGRAM PUBLIC CHANNEL FORWARDER"
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

    # =====================================================
    # IMPORTANT:
    # اول Update ها را می‌خوانیم.
    #
    # بنابراین حتی اگر CHAT_ID اشتباه باشد،
    # /id و /setdestination کار می‌کنند.
    # =====================================================

    channels, bot_state = handle_updates(
        channels,
        bot_state
    )

    # =====================================================
    # SAVE COMMAND CHANGES
    # =====================================================

    save_json(
        CHANNELS_FILE,
        channels
    )

    save_json(
        BOT_STATE_FILE,
        bot_state
    )

    # =====================================================
    # TEST DESTINATION
    # =====================================================

    if not test_destination(
        bot_state
    ):

        print("")
        print(
            "[STOP] مقصد معتبر نیست."
        )

        print(
            "[INFO] برای تعیین مقصد، "
            "داخل گروه دستور زیر را بفرست:"
        )

        print(
            "/setdestination"
        )

        print("")

        # state فعلی هم ذخیره شود
        save_json(
            STATE_FILE,
            state
        )

        return

    # =====================================================
    # CHECK CHANNELS
    # =====================================================

    state = check_channels(
        channels,
        state,
        bot_state
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
    print(
        "[DONE] اجرای برنامه تمام شد."
    )
    print("=" * 60)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
