import os
import json
import time
import re
import hashlib
from difflib import SequenceMatcher
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
ENV_CHAT_ID = os.environ["CHAT_ID"].strip()
OWNER_ID = int(os.environ["OWNER_ID"])

CHANNELS_FILE = "channels.json"
CHANNEL_KEYWORDS_FILE = "channel_keywords.json"
BANNED_WORDS_FILE = "banned_words.json"
STATE_FILE = "state.json"
BOT_STATE_FILE = "bot_state.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SEND_DELAY = 2
MAX_PROCESSED_IDS = 1000
MAX_GLOBAL_HISTORY = 1000

SIMILARITY_THRESHOLD = 0.88
MIN_SIMILARITY_LENGTH = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

FILTER_PATTERNS = [
    r"شرط[\s\u200c\u200d_ـ\-]*بندی",
    r"وین[\s\u200c\u200d_ـ\-]*تو[\s\u200c\u200d_ـ\-]*بت",
    r"وان[\s\u200c\u200d_ـ\-]*ایکس",
    r"1[\s\u200c\u200d_ـ\-._]*x[\s\u200c\u200d_ـ\-._]*bet",
]

CURRENT_CHAT_ID = ENV_CHAT_ID


class TelegramAPIError(Exception):
    def __init__(self, code, description, parameters=None):
        self.code = code
        self.description = description
        self.parameters = parameters or {}
        super().__init__(f"Telegram API error {code}: {description}")


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
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp, path)


def normalize_text(text):
    text = str(text or "")

    text = (
        text.replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
    )

    text = (
        text.replace("\u200c", " ")
        .replace("\u200d", " ")
        .replace("\ufeff", "")
        .replace("\u2060", "")
    )

    return re.sub(r"\s+", " ", text).strip().lower()


def similarity_text(text):
    text = normalize_text(text)

    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = text.replace("#", " ")

    text = re.sub(
        r"[^\w\s\u0600-\u06FF]",
        " ",
        text,
        flags=re.UNICODE
    )

    return re.sub(r"\s+", " ", text).strip()


def is_filtered(text):
    normalized = normalize_text(text)

    for pattern in FILTER_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True, pattern

    return False, None


def channel_keyword_ok(username, text, channel_keywords):
    """
    اگر این کانال هیچ کلمه‌ی فیلتری نداشته باشد، همه‌چیز مجاز است.
    اگر داشته باشد، فقط وقتی مجاز است که حداقل یکی از کلمه‌ها
    توی متن پست باشد.
    """
    required_words = channel_keywords.get(username, [])

    if not required_words:
        return True

    normalized = normalize_text(text)

    for word in required_words:
        if normalize_text(word) in normalized:
            return True

    return False


def contains_banned_word(text, banned_words):
    """
    این یک فیلتر سراسری است: اگر متن یکی از کلمات ممنوعه را
    داشته باشد، روی همه‌ی کانال‌ها اعمال می‌شود و پست ارسال
    نمی‌شود، حتی اگر شرط فیلتر مخصوص همان کانال را هم داشته باشد.
    """
    if not banned_words:
        return False

    normalized = normalize_text(text)

    for word in banned_words:
        if normalize_text(word) in normalized:
            return True

    return False


def update_chat_id(new_id):
    global CURRENT_CHAT_ID

    new_id = str(new_id).strip()

    if new_id and new_id != CURRENT_CHAT_ID:
        print("=" * 60)
        print("[MIGRATION DETECTED]")
        print(f"[OLD CHAT ID] {CURRENT_CHAT_ID}")
        print(f"[NEW CHAT ID] {new_id}")
        print("=" * 60)

    CURRENT_CHAT_ID = new_id


def telegram_call(method, destination=False, retry_migration=True, **params):
    if destination:
        params["chat_id"] = CURRENT_CHAT_ID

    try:
        response = requests.post(
            f"{API}/{method}",
            data=params,
            timeout=60
        )
    except requests.RequestException as e:
        raise TelegramAPIError(0, f"Network error: {e}")

    try:
        result = response.json()
    except Exception:
        raise TelegramAPIError(
            response.status_code,
            response.text[:500]
        )

    if result.get("ok"):
        return result

    parameters = result.get("parameters") or {}
    migrate_to = parameters.get("migrate_to_chat_id")

    if destination and migrate_to and retry_migration:
        update_chat_id(migrate_to)

        retry_params = {
            k: v for k, v in params.items()
            if k != "chat_id"
        }

        return telegram_call(
            method,
            destination=True,
            retry_migration=False,
            **retry_params
        )

    raise TelegramAPIError(
        result.get("error_code", response.status_code),
        result.get("description", "Unknown Telegram error"),
        parameters
    )


def multipart_call(method, data, files, retry_migration=True):
    data = dict(data)

    try:
        data["chat_id"] = CURRENT_CHAT_ID

        # Reset file positions before every multipart request.
        for file_obj in files.values():
            try:
                file_obj.seek(0)
            except Exception:
                pass

        response = requests.post(
            f"{API}/{method}",
            data=data,
            files=files,
            timeout=180
        )
    except requests.RequestException as e:
        raise TelegramAPIError(0, f"Network error: {e}")

    try:
        result = response.json()
    except Exception:
        raise TelegramAPIError(
            response.status_code,
            response.text[:500]
        )

    if result.get("ok"):
        return result

    parameters = result.get("parameters") or {}
    migrate_to = parameters.get("migrate_to_chat_id")

    if migrate_to and retry_migration:
        update_chat_id(migrate_to)

        return multipart_call(
            method,
            data,
            files,
            retry_migration=False
        )

    raise TelegramAPIError(
        result.get("error_code", response.status_code),
        result.get("description", "Unknown Telegram error"),
        parameters
    )


def test_destination():
    print("")
    print("=" * 60)
    print("TESTING DESTINATION")
    print("=" * 60)
    print(f"[INFO] CHAT_ID = {CURRENT_CHAT_ID}")

    try:
        result = telegram_call(
            "getChat",
            destination=True
        )

        chat = result.get("result", {})

        if chat.get("id"):
            update_chat_id(chat["id"])

        print("[OK] مقصد پیدا شد.")
        print(f"[CHAT ID] {chat.get('id')}")
        print(f"[CHAT TYPE] {chat.get('type')}")
        print(f"[CHAT TITLE] {chat.get('title')}")

        if chat.get("username"):
            print(f"[CHAT USERNAME] @{chat.get('username')}")

        print("=" * 60)
        return True

    except Exception as e:
        print("[FATAL] مقصد Telegram مشکل دارد.")
        print(f"[DETAIL] {e}")
        print("=" * 60)
        return False


def send_message(text):
    return telegram_call(
        "sendMessage",
        destination=True,
        text=text[:4096],
        disable_web_page_preview=False
    )


def send_photo(photo_url, caption=""):
    return telegram_call(
        "sendPhoto",
        destination=True,
        photo=photo_url,
        caption=caption[:1024]
    )


def send_photo_file(file_path, caption=""):
    with open(file_path, "rb") as file:
        return multipart_call(
            "sendPhoto",
            {"caption": caption[:1024]},
            {"photo": file}
        )


def send_video(video_url, caption=""):
    return telegram_call(
        "sendVideo",
        destination=True,
        video=video_url,
        caption=caption[:1024],
        supports_streaming=True
    )


def send_video_file(file_path, caption=""):
    with open(file_path, "rb") as file:
        return multipart_call(
            "sendVideo",
            {
                "caption": caption[:1024],
                "supports_streaming": "true"
            },
            {"video": file}
        )


def send_document_file(file_path, caption=""):
    with open(file_path, "rb") as file:
        return multipart_call(
            "sendDocument",
            {"caption": caption[:1024]},
            {"document": file}
        )


def download_file(url, extension="bin"):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=180
    )

    response.raise_for_status()

    # Never use the Telegram CDN URL as the filename.
    # Those URLs can contain hundreds of characters.
    extension = re.sub(
        r"[^a-zA-Z0-9]",
        "",
        extension.lower()
    )

    if not extension:
        extension = "bin"

    path = (
        f"/tmp/tg_media_"
        f"{int(time.time() * 1000)}."
        f"{extension}"
    )

    with open(path, "wb") as f:
        f.write(response.content)

    print(f"[DOWNLOAD OK] {path}")
    return path


def fetch_channel_posts(username):
    username = username.strip().lstrip("@").lower()

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
            channel_name, post_id_text = data_post.rsplit("/", 1)
            post_id = int(post_id_text)
        except Exception:
            continue

        text_div = wrap.select_one(
            ".tgme_widget_message_text"
        )

        text = (
            text_div.get_text("\n", strip=True)
            if text_div
            else ""
        )

        time_tag = wrap.select_one(
            ".tgme_widget_message_date time"
        )

        published_at = (
            time_tag.get("datetime", "")
            if time_tag
            else ""
        )

        photos = []

        for photo in wrap.select(
            "a.tgme_widget_message_photo_wrap"
        ):
            style = photo.get("style", "")

            match = re.search(
                r"url\(['\"]?([^'\")]+)",
                style
            )

            if match:
                photos.append(match.group(1))

        video_url = None

        video = wrap.select_one("video")

        if video:
            source = video.select_one("source")

            if source:
                video_url = source.get("src")

            if not video_url:
                video_url = video.get("src")

        posts.append({
            "id": post_id,
            "text": text,
            "link": f"https://t.me/{channel_name}/{post_id}",
            "photos": photos,
            "video": video_url,
            "published_at": published_at
        })

    posts.sort(key=lambda x: x["id"])

    return posts


def media_fingerprint(post):
    media = []

    for url in post.get("photos", []):
        media.append("photo:" + str(url))

    if post.get("video"):
        media.append(
            "video:" + str(post["video"])
        )

    if not media:
        return ""

    raw = "|".join(sorted(media))

    return hashlib.sha256(
        raw.encode("utf-8", errors="ignore")
    ).hexdigest()


def content_fingerprint(post):
    text = similarity_text(
        post.get("text", "")
    )

    media = media_fingerprint(post)

    raw = text + "||" + media

    if not raw.strip():
        raw = str(post.get("id", ""))

    return hashlib.sha256(
        raw.encode("utf-8", errors="ignore")
    ).hexdigest()


def text_similarity(a, b):
    a = similarity_text(a)
    b = similarity_text(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if (
        len(a) < MIN_SIMILARITY_LENGTH
        or len(b) < MIN_SIMILARITY_LENGTH
    ):
        return 0.0

    sequence_score = SequenceMatcher(
        None,
        a,
        b
    ).ratio()

    words_a = set(a.split())
    words_b = set(b.split())

    if words_a and words_b:
        token_score = (
            len(words_a & words_b)
            / len(words_a | words_b)
        )
    else:
        token_score = 0.0

    return max(
        sequence_score,
        token_score
    )


def find_duplicate(post, history):
    fingerprint = content_fingerprint(post)
    media_fp = media_fingerprint(post)

    for item in reversed(history):
        if item.get("fingerprint") == fingerprint:
            return item, "exact content"

    if media_fp:
        for item in reversed(history):
            if item.get("media_fingerprint") != media_fp:
                continue

            old_text = item.get("text", "")
            new_text = post.get("text", "")

            if not old_text or not new_text:
                return item, "same media"

            score = text_similarity(
                new_text,
                old_text
            )

            if score >= 0.70:
                return item, (
                    f"same media + similar text {score:.2f}"
                )

    for item in reversed(history):
        old_text = item.get("text", "")

        if not old_text:
            continue

        score = text_similarity(
            post.get("text", ""),
            old_text
        )

        if score >= SIMILARITY_THRESHOLD:
            return item, f"similar text {score:.2f}"

    return None, None


def build_caption(username, text, link, sources=None):
    sources = sources or []

    caption = (
        f"📢 @{username}\n\n"
        f"{text}\n\n"
        f"🔗 {link}"
    )

    unique_sources = list(
        dict.fromkeys(sources)
    )

    if len(unique_sources) > 1:
        caption += (
            "\n\n📚 کانال‌های منتشرکننده همین محتوا:\n"
            + "\n".join(
                f"• @{source}"
                for source in unique_sources
            )
        )

    return caption


def add_source_to_original(item, username):
    sources = item.setdefault(
        "sources",
        []
    )

    if username in sources:
        return

    message_id = item.get("message_id")

    if not message_id:
        # Keep the source in history even when there is no editable
        # destination message available.
        sources.append(username)
        return

    new_sources = list(sources) + [username]

    caption = build_caption(
        item.get("original_username", ""),
        item.get("original_text", ""),
        item.get("original_link", ""),
        new_sources
    )

    try:
        if item.get("message_kind") == "text":
            telegram_call(
                "editMessageText",
                destination=True,
                message_id=message_id,
                text=caption[:4096]
            )
        else:
            telegram_call(
                "editMessageCaption",
                destination=True,
                message_id=message_id,
                caption=caption[:1024]
            )

        sources.append(username)

        print(
            f"[SOURCE UPDATED] +@{username}"
        )

    except Exception as e:
        print(
            f"[WARN] بروزرسانی منابع ناموفق بود: {e}"
        )


def send_post(post, username):
    text = (
        post.get("text") or ""
    ).strip()

    link = post["link"]

    filtered, pattern = is_filtered(text)

    if filtered:
        print(
            f"[FILTERED] @{username} "
            f"post={post['id']} "
            f"pattern={pattern}"
        )

        return {
            "success": True,
            "type": "filtered",
            "result": None,
            "message_kind": None
        }

    caption = build_caption(
        username,
        text,
        link
    )

    photos = post.get("photos", [])
    video = post.get("video")

    if not photos and not video:
        try:
            result = send_message(caption)

            return {
                "success": True,
                "type": "sent",
                "result": result,
                "message_kind": "text"
            }

        except Exception as e:
            print(
                f"[ERROR] ارسال متن: {e}"
            )
            return {"success": False}

    if photos:
        first_result = None
        sent_count = 0

        for index, photo_url in enumerate(photos):
            photo_caption = (
                caption
                if index == 0
                else ""
            )

            try:
                result = send_photo(
                    photo_url,
                    photo_caption
                )

                if index == 0:
                    first_result = result

                sent_count += 1

                print(
                    f"[OK] عکس "
                    f"{index + 1}/{len(photos)} ارسال شد."
                )

            except Exception as e:
                print(
                    f"[WARN] ارسال مستقیم عکس: {e}"
                )

                local_file = None

                try:
                    local_file = download_file(
                        photo_url,
                        "jpg"
                    )

                    try:
                        result = send_photo_file(
                            local_file,
                            photo_caption
                        )

                        if index == 0:
                            first_result = result

                        sent_count += 1

                        print(
                            f"[OK] عکس "
                            f"{index + 1}/{len(photos)} "
                            f"به صورت فایل تصویری ارسال شد."
                        )

                    except Exception as e2:
                        print(
                            f"[WARN] آپلود عکس به صورت photo: {e2}"
                        )

                        # Last fallback: send as document.
                        result = send_document_file(
                            local_file,
                            photo_caption
                        )

                        if index == 0:
                            first_result = result

                        sent_count += 1

                        print(
                            f"[OK] عکس "
                            f"{index + 1}/{len(photos)} "
                            f"به صورت فایل ارسال شد."
                        )

                except Exception as e2:
                    print(
                        f"[ERROR] ارسال عکس: {e2}"
                    )

                finally:
                    if local_file and os.path.exists(local_file):
                        os.remove(local_file)

        return {
            "success": sent_count > 0,
            "type": "sent",
            "result": first_result,
            "message_kind": "caption"
        }

    if video:
        try:
            result = send_video(
                video,
                caption
            )

            print("[OK] ویدیو ارسال شد.")

            return {
                "success": True,
                "type": "sent",
                "result": result,
                "message_kind": "caption"
            }

        except Exception as e:
            print(
                f"[WARN] ارسال مستقیم ویدیو: {e}"
            )

        local_file = None

        try:
            local_file = download_file(
                video,
                "mp4"
            )

            try:
                result = send_video_file(
                    local_file,
                    caption
                )

                print(
                    "[OK] ویدیو به صورت ویدیو آپلود شد."
                )

                return {
                    "success": True,
                    "type": "sent",
                    "result": result,
                    "message_kind": "caption"
                }

            except Exception as e2:
                print(
                    f"[WARN] آپلود ویدیو به صورت video: {e2}"
                )

                result = send_document_file(
                    local_file,
                    caption
                )

                print(
                    "[OK] ویدیو به صورت فایل ارسال شد."
                )

                return {
                    "success": True,
                    "type": "sent",
                    "result": result,
                    "message_kind": "caption"
                }

        except Exception as e:
            print(
                f"[WARN] آپلود ویدیو: {e}"
            )

        finally:
            if local_file and os.path.exists(local_file):
                os.remove(local_file)

        try:
            result = send_message(
                f"🎬 پست جدید از @{username}\n\n"
                f"{text}\n\n"
                f"🔗 {link}\n\n"
                "⚠️ ارسال مستقیم ویدیو ناموفق بود."
            )

            return {
                "success": True,
                "type": "link",
                "result": result,
                "message_kind": "text"
            }

        except Exception as e:
            print(
                f"[ERROR] ارسال لینک ویدیو: {e}"
            )

    return {"success": False}


HELP_TEXT = (
    "🤖 ربات ارسال پست\n\n"
    "/add username - افزودن کانال\n"
    "/remove username - حذف کانال\n"
    "/list - لیست کانال‌ها\n"
    "/id - نمایش شناسه چت فعلی\n"
    "\n"
    "فیلتر کلمه (فقط روی یک کانال خاص):\n"
    "/addword username کلمه - این کانال فقط پست‌های حاوی این کلمه رو بفرسته\n"
    "/removeword username کلمه - حذف یک کلمه از فیلتر این کانال\n"
    "/clearword username - حذف کامل فیلتر این کانال (دوباره همه‌چیز بیاد)\n"
    "/words - نمایش همه‌ی فیلترهای فعال\n"
    "\n"
    "کلمات ممنوعه (روی همه‌ی کانال‌ها، بدون استثنا):\n"
    "/addban کلمه - افزودن کلمه به لیست ممنوعه‌ی سراسری\n"
    "/removeban کلمه - حذف کلمه از لیست ممنوعه\n"
    "/bans - نمایش لیست کلمات ممنوعه\n"
    "\n"
    "گزارش:\n"
    "/report - تعداد پست‌های ارسالی هر کانال\n"
    "\n"
    "/help - راهنما"
)


def handle_updates(channels, channel_keywords, banned_words, state, bot_state):
    offset = int(
        bot_state.get(
            "last_update_id",
            0
        )
    ) + 1

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
        return channels, channel_keywords, banned_words, bot_state

    for update in updates:
        bot_state["last_update_id"] = (
            update["update_id"]
        )

        message = update.get("message")

        if not message:
            continue

        user_id = (
            message.get("from", {})
            .get("id")
        )

        chat_id = (
            message.get("chat", {})
            .get("id")
        )

        text = (
            message.get("text") or ""
        ).strip()

        if not text:
            continue

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

        if command == "/id":
            send_message_to_chat(
                chat_id,
                f"🆔 Chat ID:\n{chat_id}"
            )

        elif command in (
            "/start",
            "/help",
            "/manage"
        ):
            send_message_to_chat(
                chat_id,
                HELP_TEXT
            )

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

            channels.append(username)

            send_message_to_chat(
                chat_id,
                f"✅ @{username} اضافه شد."
            )

        elif command == "/remove":
            username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            old_length = len(channels)

            channels = [
                c for c in channels
                if c.lower().lstrip("@") != username
            ]

            if len(channels) < old_length:
                message_text = (
                    f"🗑 @{username} حذف شد."
                )
            else:
                message_text = (
                    f"❌ @{username} پیدا نشد."
                )

            send_message_to_chat(
                chat_id,
                message_text
            )

        elif command == "/list":
            if channels:
                message_text = (
                    "📋 کانال‌های فعال:\n\n"
                    + "\n".join(
                        f"• @{c}"
                        for c in channels
                    )
                )
            else:
                message_text = (
                    "📋 لیست کانال‌ها خالی است."
                )

            send_message_to_chat(
                chat_id,
                message_text
            )

        elif command == "/addword":
            sub_parts = argument.split(maxsplit=1)

            if len(sub_parts) < 2:
                send_message_to_chat(
                    chat_id,
                    "مثال:\n/addword varzesh3 پرسپولیس"
                )
                continue

            word_username = (
                sub_parts[0]
                .lstrip("@")
                .strip()
                .lower()
            )
            word = sub_parts[1].strip()

            words = channel_keywords.setdefault(
                word_username,
                []
            )

            if word in words:
                send_message_to_chat(
                    chat_id,
                    f"⚠️ «{word}» از قبل روی @{word_username} فعاله."
                )
                continue

            words.append(word)

            tracked = [
                c.lower().lstrip("@")
                for c in channels
            ]

            note = (
                ""
                if word_username in tracked
                else (
                    "\n⚠️ توجه: این کانال هنوز با /add "
                    "اضافه نشده، اول اضافه‌اش کن."
                )
            )

            send_message_to_chat(
                chat_id,
                f"✅ فیلتر «{word}» روی @{word_username} فعال شد.{note}"
            )

        elif command == "/removeword":
            sub_parts = argument.split(maxsplit=1)

            if len(sub_parts) < 2:
                send_message_to_chat(
                    chat_id,
                    "مثال:\n/removeword varzesh3 پرسپولیس"
                )
                continue

            word_username = (
                sub_parts[0]
                .lstrip("@")
                .strip()
                .lower()
            )
            word = sub_parts[1].strip()

            words = channel_keywords.get(
                word_username,
                []
            )

            if word in words:
                words.remove(word)

                if not words:
                    channel_keywords.pop(
                        word_username,
                        None
                    )

                send_message_to_chat(
                    chat_id,
                    f"🗑 «{word}» از فیلتر @{word_username} حذف شد."
                )
            else:
                send_message_to_chat(
                    chat_id,
                    "همچین کلمه‌ای روی این کانال فعال نیست."
                )

        elif command == "/clearword":
            word_username = (
                argument
                .lstrip("@")
                .strip()
                .lower()
            )

            if word_username in channel_keywords:
                channel_keywords.pop(
                    word_username,
                    None
                )
                send_message_to_chat(
                    chat_id,
                    f"🗑 فیلتر @{word_username} کامل حذف شد "
                    "(الان همه‌چیزش میاد)."
                )
            else:
                send_message_to_chat(
                    chat_id,
                    "این کانال فیلتری نداشت."
                )

        elif command == "/words":
            if channel_keywords:
                lines = [
                    f"• @{uname}: " + "، ".join(words)
                    for uname, words in channel_keywords.items()
                    if words
                ]

                message_text = (
                    "🏷 فیلترهای فعال:\n\n" + "\n".join(lines)
                    if lines
                    else "هیچ فیلتری فعال نیست."
                )
            else:
                message_text = "هیچ فیلتری فعال نیست."

            send_message_to_chat(
                chat_id,
                message_text
            )

        elif command == "/addban":
            word = argument.strip()

            if not word:
                send_message_to_chat(
                    chat_id,
                    "کلمه رو هم بنویس، مثلاً:\n/addban شرط‌بندی"
                )
                continue

            if word in banned_words:
                send_message_to_chat(
                    chat_id,
                    f"⚠️ «{word}» از قبل توی لیست ممنوعه هست."
                )
                continue

            banned_words.append(word)

            send_message_to_chat(
                chat_id,
                f"🚫 «{word}» به لیست ممنوعه‌ی سراسری اضافه شد "
                "(روی همه‌ی کانال‌ها اعمال می‌شه)."
            )

        elif command == "/removeban":
            word = argument.strip()

            if word in banned_words:
                banned_words.remove(word)

                send_message_to_chat(
                    chat_id,
                    f"🗑 «{word}» از لیست ممنوعه حذف شد."
                )
            else:
                send_message_to_chat(
                    chat_id,
                    "همچین کلمه‌ای توی لیست ممنوعه نیست."
                )

        elif command == "/bans":
            if banned_words:
                message_text = (
                    "🚫 کلمات ممنوعه‌ی فعلی:\n\n"
                    + "\n".join(
                        f"• {word}"
                        for word in banned_words
                    )
                )
            else:
                message_text = "هیچ کلمه‌ی ممنوعه‌ای تنظیم نشده."

            send_message_to_chat(
                chat_id,
                message_text
            )

        elif command == "/report":
            channel_states = state.get(
                "channels",
                {}
            )

            report_lines = []

            for raw_username in channels:
                clean_username = (
                    raw_username
                    .strip()
                    .lstrip("@")
                    .lower()
                )

                count = channel_states.get(
                    clean_username,
                    {}
                ).get(
                    "sent_count",
                    0
                )

                report_lines.append(
                    f"• @{clean_username}: {count} پست"
                )

            if report_lines:
                message_text = (
                    "📊 گزارش تعداد پست‌های ارسالی:\n\n"
                    + "\n".join(report_lines)
                )
            else:
                message_text = "هنوز هیچ کانالی اضافه نشده."

            send_message_to_chat(
                chat_id,
                message_text
            )

        else:
            send_message_to_chat(
                chat_id,
                "❌ دستور ناشناخته است.\n\n"
                + HELP_TEXT
            )

    return channels, channel_keywords, banned_words, bot_state


def send_message_to_chat(chat_id, text):
    return telegram_call(
        "sendMessage",
        chat_id=chat_id,
        text=text[:4096]
    )


def normalize_state(raw):
    if (
        isinstance(raw, dict)
        and isinstance(
            raw.get("channels"),
            dict
        )
    ):
        result_channels = {}

        for name, value in raw["channels"].items():
            if not isinstance(value, dict):
                value = {}

            processed_ids = []

            for item in value.get(
                "processed_ids",
                []
            ):
                try:
                    processed_ids.append(
                        int(item)
                    )
                except Exception:
                    pass

            try:
                last_id = int(
                    value.get(
                        "last_id",
                        0
                    )
                )
            except Exception:
                last_id = 0

            try:
                sent_count = int(
                    value.get(
                        "sent_count",
                        0
                    )
                )
            except Exception:
                sent_count = 0

            result_channels[name] = {
                "last_id": last_id,
                "processed_ids": processed_ids[
                    -MAX_PROCESSED_IDS:
                ],
                "sent_count": sent_count
            }

        global_data = raw.get(
            "global",
            {}
        )

        if not isinstance(
            global_data,
            dict
        ):
            global_data = {}

        history = global_data.get(
            "history",
            []
        )

        if not isinstance(
            history,
            list
        ):
            history = []

        return {
            "channels": result_channels,
            "global": {
                "history": history[
                    -MAX_GLOBAL_HISTORY:
                ]
            }
        }

    channels = {}

    if isinstance(raw, dict):
        for name, value in raw.items():
            try:
                last_id = int(value)
            except Exception:
                last_id = 0

            channels[name] = {
                "last_id": last_id,
                "processed_ids": [],
                "sent_count": 0
            }

    return {
        "channels": channels,
        "global": {
            "history": []
        }
    }


def published_timestamp(post):
    value = post.get(
        "published_at",
        ""
    )

    if not value:
        return 0

    try:
        if value.endswith("Z"):
            value = (
                value[:-1]
                + "+00:00"
            )

        dt = datetime.fromisoformat(
            value
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.timestamp()

    except Exception:
        return 0


def mark_processed(
    channel_state,
    post_id
):
    processed_ids = channel_state.setdefault(
        "processed_ids",
        []
    )

    if post_id not in processed_ids:
        processed_ids.append(post_id)

    channel_state["last_id"] = max(
        int(
            channel_state.get(
                "last_id",
                0
            )
        ),
        post_id
    )

    channel_state["processed_ids"] = (
        processed_ids[
            -MAX_PROCESSED_IDS:
        ]
    )


def add_history(
    history,
    post,
    username,
    result,
    message_kind
):
    message = {}

    if isinstance(result, dict):
        message = result.get(
            "result",
            {}
        )

        if not isinstance(
            message,
            dict
        ):
            message = {}

    history.append({
        "fingerprint": content_fingerprint(post),
        "media_fingerprint": media_fingerprint(post),
        "text": post.get("text", ""),
        "original_username": username,
        "original_text": post.get("text", ""),
        "original_link": post.get("link", ""),
        "post_id": post.get("id"),
        "message_id": message.get("message_id"),
        "message_kind": message_kind,
        "sources": [username],
        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    })

    del history[:-MAX_GLOBAL_HISTORY]


def check_channels(channels, channel_keywords, banned_words, state):
    channel_states = state["channels"]
    history = state["global"]["history"]

    candidates = []

    for channel_index, username in enumerate(channels):
        username = (
            username
            .strip()
            .lstrip("@")
            .lower()
        )

        print("")
        print(f"[CHECK] @{username}")

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
            f"[FOUND] @{username}: "
            f"{len(posts)} posts"
        )

        if username not in channel_states:
            channel_states[username] = {
                "last_id": 0,
                "processed_ids": [],
                "sent_count": 0
            }

        channel_state = (
            channel_states[username]
        )

        if int(
            channel_state.get(
                "last_id",
                0
            )
        ) == 0:

            if posts:
                latest = posts[-1]

                mark_processed(
                    channel_state,
                    latest["id"]
                )

                print(
                    f"[INIT] @{username} "
                    f"baseline={latest['id']}"
                )

            continue

        for post in posts:
            post_id = int(
                post["id"]
            )

            if post_id <= int(
                channel_state.get(
                    "last_id",
                    0
                )
            ):
                continue

            if post_id in channel_state.get(
                "processed_ids",
                []
            ):
                continue

            candidates.append({
                "username": username,
                "channel_index": channel_index,
                "post": post
            })

    candidates.sort(
        key=lambda item: (
            published_timestamp(
                item["post"]
            ),
            item["channel_index"],
            item["post"]["id"]
        )
    )

    print(
        f"[GLOBAL] new candidates="
        f"{len(candidates)}"
    )

    for item in candidates:
        username = item["username"]
        post = item["post"]
        post_id = int(post["id"])

        channel_state = (
            channel_states[username]
        )

        filtered, pattern = is_filtered(
            post.get("text", "")
        )

        if filtered:
            print(
                f"[FILTERED] @{username} "
                f"post={post_id} "
                f"pattern={pattern}"
            )

            mark_processed(
                channel_state,
                post_id
            )

            save_json(
                STATE_FILE,
                state
            )

            continue

        if contains_banned_word(
            post.get("text", ""),
            banned_words
        ):
            print(
                f"[BANNED] @{username} "
                f"post={post_id}"
            )

            mark_processed(
                channel_state,
                post_id
            )

            save_json(
                STATE_FILE,
                state
            )

            continue

        if not channel_keyword_ok(
            username,
            post.get("text", ""),
            channel_keywords
        ):
            print(
                f"[KEYWORD SKIP] @{username} "
                f"post={post_id}"
            )

            mark_processed(
                channel_state,
                post_id
            )

            save_json(
                STATE_FILE,
                state
            )

            continue

        duplicate, reason = find_duplicate(
            post,
            history
        )

        if duplicate:
            print(
                f"[GLOBAL DUPLICATE] "
                f"@{username} post={post_id} "
                f"reason={reason}"
            )

            add_source_to_original(
                duplicate,
                username
            )

            mark_processed(
                channel_state,
                post_id
            )

            save_json(
                STATE_FILE,
                state
            )

            continue

        result = send_post(
            post,
            username
        )

        if not result.get("success"):
            print(
                f"[FAILED] @{username} "
                f"post={post_id}"
            )

            print(
                "[STATE] این پست عمداً "
                "پردازش‌شده ثبت نشد تا اجرای بعدی دوباره تلاش کند."
            )

            continue

        mark_processed(
            channel_state,
            post_id
        )

        channel_state["sent_count"] = (
            int(
                channel_state.get(
                    "sent_count",
                    0
                )
            )
            + 1
        )

        if result.get("type") != "filtered":
            add_history(
                history,
                post,
                username,
                result.get("result"),
                result.get("message_kind")
            )

        save_json(
            STATE_FILE,
            state
        )

        time.sleep(SEND_DELAY)

    return state


def main():
    global CURRENT_CHAT_ID

    channels = load_json(
        CHANNELS_FILE,
        []
    )

    channel_keywords = load_json(
        CHANNEL_KEYWORDS_FILE,
        {}
    )

    banned_words = load_json(
        BANNED_WORDS_FILE,
        []
    )

    state = normalize_state(
        load_json(
            STATE_FILE,
            {}
        )
    )

    bot_state = load_json(
        BOT_STATE_FILE,
        {"last_update_id": 0}
    )

    if not isinstance(
        bot_state,
        dict
    ):
        bot_state = {
            "last_update_id": 0
        }

    CURRENT_CHAT_ID = str(
        bot_state.get(
            "destination_chat_id",
            ENV_CHAT_ID
        )
    ).strip()

    print("")
    print("=" * 60)
    print("TELEGRAM PUBLIC CHANNEL FORWARDER")
    print("=" * 60)
    print(
        f"[INFO] تعداد کانال‌ها: {len(channels)}"
    )
    print(
        f"[INFO] مقصد فعلی: {CURRENT_CHAT_ID}"
    )

    if not test_destination():
        print(
            "[STOP] مقصد معتبر نیست."
        )
        return

    channels, channel_keywords, banned_words, bot_state = handle_updates(
        channels,
        channel_keywords,
        banned_words,
        state,
        bot_state
    )

    state = check_channels(
        channels,
        channel_keywords,
        banned_words,
        state
    )

    bot_state["destination_chat_id"] = (
        CURRENT_CHAT_ID
    )

    save_json(
        CHANNELS_FILE,
        channels
    )

    save_json(
        CHANNEL_KEYWORDS_FILE,
        channel_keywords
    )

    save_json(
        BANNED_WORDS_FILE,
        banned_words
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
        f"[FINAL CHAT ID] {CURRENT_CHAT_ID}"
    )
    print("[DONE] اجرای برنامه تمام شد.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("[STOP] متوقف شد.")

    except Exception as e:
        import traceback

        print("=" * 60)
        print("[FATAL ERROR]")
        print(
            f"[ERROR TYPE] {type(e).__name__}"
        )
        print(
            f"[ERROR] {e}"
        )
        traceback.print_exc()
        print("=" * 60)

        raise
