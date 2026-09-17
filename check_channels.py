import os
import json
import time
import re
import hashlib
import requests
from bs4 import BeautifulSoup


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
ENV_CHAT_ID = os.environ["CHAT_ID"].strip()
OWNER_ID = int(os.environ["OWNER_ID"])

CHANNELS_FILE = "channels.json"
STATE_FILE = "state.json"
BOT_STATE_FILE = "bot_state.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

MAX_PROCESSED_IDS = 1000
MAX_FINGERPRINTS = 500

REQUEST_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 180

SEND_DELAY = 2


# =========================================================
# HTTP HEADERS
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


# =========================================================
# FILTER
# =========================================================

# فیلتر سخت‌گیرانه تبلیغات شرط‌بندی
#
# این الگوها شکل‌های مختلف زیر را می‌گیرند:
#
# شرط بندی
# شرط‌بندی
# شرط‌بندی
# شرطبندی
#
# وینتوبت
# وین تو بت
#
# وان ایکس
# وان‌ایکس
#
# 1xbet
# 1x bet
# 1-x-bet
# 1x.bet
#

FILTER_PATTERNS = [
    r"شرط[\s\u200c\u200d_ـ\-]*بندی",
    r"وین[\s\u200c\u200d_ـ\-]*تو[\s\u200c\u200d_ـ\-]*بت",
    r"وان[\s\u200c\u200d_ـ\-]*ایکس",
    r"1[\s\u200c\u200d_ـ\-._]*x[\s\u200c\u200d_ـ\-._]*bet",
]


def normalize_text(text):
    """
    نرمال‌سازی متن فارسی برای:
    - یکسان کردن ی / ي
    - یکسان کردن ک / ك
    - حذف نیم‌فاصله‌های اضافی
    - حذف فاصله‌های تکراری
    - lowercase برای متن انگلیسی
    """

    if not text:
        return ""

    text = str(text)

    text = text.replace("ي", "ی")
    text = text.replace("ى", "ی")
    text = text.replace("ك", "ک")

    # حذف انواع ZWNJ / ZWJ
    text = text.replace("\u200c", " ")
    text = text.replace("\u200d", " ")

    # حذف کاراکترهای نامرئی
    text = text.replace("\ufeff", "")
    text = text.replace("\u2060", "")

    # یکسان‌سازی فاصله
    text = re.sub(r"\s+", " ", text)

    return text.strip().lower()


def contains_filtered_content(text):
    """
    بررسی متن پست برای کلمات ممنوع.
    """

    normalized = normalize_text(text)

    if not normalized:
        return False, None

    for pattern in FILTER_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return True, pattern

    return False, None


# =========================================================
# FILE / JSON
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
    temp_path = f"{path}.tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_path, path)

    except Exception as e:
        print(f"[ERROR] ذخیره {path}: {e}")


# =========================================================
# STATE NORMALIZATION
# =========================================================

def normalize_channel_state(raw_value):
    """
    state.json قدیمی ممکن است به شکل:

    {
        "channel": 123
    }

    باشد.

    نسخه جدید:

    {
        "channel": {
            "last_id": 123,
            "processed_ids": [],
            "fingerprints": []
        }
    }

    این تابع هر دو حالت را پشتیبانی می‌کند.
    """

    if isinstance(raw_value, dict):
        last_id = raw_value.get("last_id", 0)

        try:
            last_id = int(last_id)
        except Exception:
            last_id = 0

        processed_ids = raw_value.get(
            "processed_ids",
            []
        )

        fingerprints = raw_value.get(
            "fingerprints",
            []
        )

        if not isinstance(processed_ids, list):
            processed_ids = []

        if not isinstance(fingerprints, list):
            fingerprints = []

        clean_ids = []

        for item in processed_ids:
            try:
                clean_ids.append(int(item))
            except Exception:
                pass

        fingerprints = [
            str(x)
            for x in fingerprints
            if x
        ]

        return {
            "last_id": last_id,
            "processed_ids": clean_ids[-MAX_PROCESSED_IDS:],
            "fingerprints": fingerprints[-MAX_FINGERPRINTS:]
        }

    # سازگاری با state قدیمی
    try:
        old_last_id = int(raw_value)
    except Exception:
        old_last_id = 0

    return {
        "last_id": old_last_id,
        "processed_ids": [],
        "fingerprints": []
    }


def normalize_full_state(state):
    if not isinstance(state, dict):
        state = {}

    normalized = {}

    for username, value in state.items():
        normalized[username] = normalize_channel_state(value)

    return normalized


# =========================================================
# DESTINATION CHAT ID
# =========================================================

def get_current_chat_id(bot_state):
    """
    اولویت:
    1. شناسه‌ای که قبلاً به دلیل migration ذخیره شده
    2. CHAT_ID موجود در GitHub Secrets
    """

    saved_id = bot_state.get("destination_chat_id")

    if saved_id:
        return str(saved_id).strip()

    return ENV_CHAT_ID


CURRENT_CHAT_ID = ENV_CHAT_ID


def update_destination_chat_id(new_chat_id):
    """
    شناسه فعلی مقصد را در حافظه تغییر می‌دهد.
    ذخیره دائمی در main انجام می‌شود.
    """

    global CURRENT_CHAT_ID

    new_chat_id = str(new_chat_id).strip()

    if not new_chat_id:
        return

    if CURRENT_CHAT_ID != new_chat_id:
        print("")
        print("=" * 60)
        print("[MIGRATION DETECTED]")
        print(f"[OLD CHAT ID] {CURRENT_CHAT_ID}")
        print(f"[NEW CHAT ID] {new_chat_id}")
        print("[INFO] مقصد به Supergroup منتقل شده است.")
        print("=" * 60)

    CURRENT_CHAT_ID = new_chat_id


# =========================================================
# TELEGRAM EXCEPTION
# =========================================================

class TelegramAPIError(Exception):

    def __init__(
        self,
        error_code,
        description,
        parameters=None
    ):
        self.error_code = error_code
        self.description = description
        self.parameters = parameters or {}

        message = (
            f"Telegram API error "
            f"{error_code}: {description}"
        )

        super().__init__(message)


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_call(method, retry_migration=True, **params):
    """
    درخواست معمولی به Telegram Bot API.

    اگر Telegram بگوید گروه به Supergroup منتقل شده:
    migrate_to_chat_id را می‌گیرد،
    CHAT_ID را عوض می‌کند،
    و همان درخواست را دوباره اجرا می‌کند.
    """

    if "chat_id" not in params:
        params["chat_id"] = CURRENT_CHAT_ID

    else:
        # هر جا chat_id مقصد خود ربات است
        # از شناسه فعلی استفاده شود.
        if params["chat_id"] == ENV_CHAT_ID:
            params["chat_id"] = CURRENT_CHAT_ID

    url = f"{API}/{method}"

    try:
        response = requests.post(
            url,
            data=params,
            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as e:
        raise TelegramAPIError(
            0,
            f"Network error: {e}"
        )

    try:
        result = response.json()

    except Exception:
        raise TelegramAPIError(
            response.status_code,
            (
                f"Telegram returned HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )
        )

    if result.get("ok"):
        return result

    error_code = result.get(
        "error_code",
        response.status_code
    )

    description = result.get(
        "description",
        "Unknown Telegram error"
    )

    parameters_info = result.get(
        "parameters",
        {}
    )

    migrate_to = parameters_info.get(
        "migrate_to_chat_id"
    )

    # -----------------------------------------------------
    # AUTO MIGRATION
    # -----------------------------------------------------

    if migrate_to and retry_migration:

        print("")
        print(
            "[TELEGRAM] Telegram اعلام کرد "
            "گروه به Supergroup تبدیل شده."
        )

        print(
            f"[TELEGRAM] migrate_to_chat_id = "
            f"{migrate_to}"
        )

        update_destination_chat_id(
            migrate_to
        )

        # دوباره همان درخواست
        params["chat_id"] = CURRENT_CHAT_ID

        return telegram_call(
            method,
            retry_migration=False,
            **params
        )

    raise TelegramAPIError(
        error_code,
        description,
        parameters_info
    )


# =========================================================
# MULTIPART TELEGRAM API
# =========================================================

def telegram_multipart_call(
    method,
    data=None,
    files=None,
    retry_migration=True
):
    """
    برای ارسال فایل‌هایی مثل sendDocument.

    چون requests multipart استفاده می‌کنیم،
    telegram_call معمولی مناسب این بخش نیست.
    """

    if data is None:
        data = {}

    data = dict(data)

    data["chat_id"] = CURRENT_CHAT_ID

    url = f"{API}/{method}"

    try:
        response = requests.post(
            url,
            data=data,
            files=files,
            timeout=DOWNLOAD_TIMEOUT
        )

    except requests.RequestException as e:
        raise TelegramAPIError(
            0,
            f"Network error: {e}"
        )

    try:
        result = response.json()

    except Exception:
        raise TelegramAPIError(
            response.status_code,
            (
                f"Telegram HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )
        )

    if result.get("ok"):
        return result

    error_code = result.get(
        "error_code",
        response.status_code
    )

    description = result.get(
        "description",
        "Unknown Telegram error"
    )

    parameters_info = result.get(
        "parameters",
        {}
    )

    migrate_to = parameters_info.get(
        "migrate_to_chat_id"
    )

    if migrate_to and retry_migration:

        print(
            "[TELEGRAM] Multipart migration detected."
        )

        update_destination_chat_id(
            migrate_to
        )

        data["chat_id"] = CURRENT_CHAT_ID

        return telegram_multipart_call(
            method,
            data=data,
            files=files,
            retry_migration=False
        )

    raise TelegramAPIError(
        error_code,
        description,
        parameters_info
    )


# =========================================================
# TEST DESTINATION
# =========================================================

def test_destination():
    print("")
    print("=" * 60)
    print("TESTING DESTINATION CHAT")
    print("=" * 60)

    print(
        f"[INFO] CHAT_ID = "
        f"{CURRENT_CHAT_ID}"
    )

    try:

        result = telegram_call(
            "getChat",
            chat_id=CURRENT_CHAT_ID,
            retry_migration=True
        )

        chat = result.get(
            "result",
            {}
        )

        actual_id = chat.get("id")

        if actual_id:
            update_destination_chat_id(
                actual_id
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

    except TelegramAPIError as e:

        print("")
        print(
            "[FATAL] مقصد Telegram مشکل دارد."
        )

        print(
            f"[DETAIL] {e}"
        )

        print("")
        print(
            "CHAT_ID باید شناسه واقعی گروه "
            "یا Supergroup باشد."
        )

        print("=" * 60)

        return False


# =========================================================
# SEND MESSAGE
# =========================================================

def send_message(
    text,
    chat_id=None
):
    target = (
        chat_id
        if chat_id is not None
        else CURRENT_CHAT_ID
    )

    return telegram_call(
        "sendMessage",
        chat_id=target,
        text=text[:4096],
        disable_web_page_preview=False
    )


def send_photo(
    photo_url,
    caption=""
):
    return telegram_call(
        "sendPhoto",
        chat_id=CURRENT_CHAT_ID,
        photo=photo_url,
        caption=caption[:1024]
    )


def send_video(
    video_url,
    caption=""
):
    return telegram_call(
        "sendVideo",
        chat_id=CURRENT_CHAT_ID,
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
        timeout=DOWNLOAD_TIMEOUT
    )

    response.raise_for_status()

    filename = (
        url.split("?")[0]
        .rstrip("/")
        .split("/")[-1]
    )

    if not filename:
        filename = "telegram_media"

    # جلوگیری از نام فایل خراب
    filename = re.sub(
        r"[^a-zA-Z0-9._-]",
        "_",
        filename
    )

    path = (
        f"/tmp/"
        f"tg_media_{int(time.time() * 1000)}_"
        f"{filename}"
    )

    with open(path, "wb") as f:
        f.write(response.content)

    print(
        f"[DOWNLOAD OK] "
        f"{url[:100]} -> {path}"
    )

    return path


# =========================================================
# SEND DOCUMENT
# =========================================================

def send_document_file(
    file_path,
    caption=""
):
    with open(file_path, "rb") as file:

        return telegram_multipart_call(
            "sendDocument",
            data={
                "chat_id": CURRENT_CHAT_ID,
                "caption": caption[:1024]
            },
            files={
                "document": file
            }
        )


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
        timeout=REQUEST_TIMEOUT
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
        # TEXT / CAPTION
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

            match = re.search(
                r"url\(['\"]?([^'\")]+)",
                style
            )

            if match:
                photos.append(
                    match.group(1)
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
# CONTENT FINGERPRINT
# =========================================================

def create_content_fingerprint(post):
    """
    برای ضد تکرار سخت‌گیرانه.

    post_id در fingerprint استفاده نمی‌شود،
    چون اگر همان محتوا با ID دیگری منتشر شود
    باز هم قابل تشخیص باشد.
    """

    text = normalize_text(
        post.get("text", "")
    )

    photos = post.get(
        "photos",
        []
    )

    video = post.get(
        "video"
    )

    media_parts = []

    for photo in photos:
        media_parts.append(
            "photo:" +
            str(photo).strip()
        )

    if video:
        media_parts.append(
            "video:" +
            str(video).strip()
        )

    raw = (
        text
        + "||"
        + "|".join(media_parts)
    )

    # اگر پست کاملاً خالی باشد
    if not raw.strip():
        raw = str(
            post.get("id", "")
        )

    fingerprint = hashlib.sha256(
        raw.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()

    return fingerprint


# =========================================================
# DUPLICATE CHECK
# =========================================================

def is_duplicate_post(
    post,
    channel_state
):
    post_id = int(
        post["id"]
    )

    last_id = int(
        channel_state.get(
            "last_id",
            0
        )
    )

    processed_ids = channel_state.get(
        "processed_ids",
        []
    )

    fingerprints = channel_state.get(
        "fingerprints",
        []
    )

    # -----------------------------------------------------
    # روش اول: ID
    # -----------------------------------------------------

    if post_id <= last_id:
        return True, "post_id <= last_id"

    if post_id in processed_ids:
        return True, "post_id already processed"

    # -----------------------------------------------------
    # روش دوم: Fingerprint
    # -----------------------------------------------------

    fingerprint = create_content_fingerprint(
        post
    )

    if fingerprint in fingerprints:
        return True, "content fingerprint already processed"

    return False, None


# =========================================================
# MARK POST AS PROCESSED
# =========================================================

def mark_post_processed(
    channel_state,
    post
):
    post_id = int(
        post["id"]
    )

    fingerprint = create_content_fingerprint(
        post
    )

    processed_ids = channel_state.setdefault(
        "processed_ids",
        []
    )

    fingerprints = channel_state.setdefault(
        "fingerprints",
        []
    )

    if post_id not in processed_ids:
        processed_ids.append(
            post_id
        )

    if fingerprint not in fingerprints:
        fingerprints.append(
            fingerprint
        )

    # -----------------------------------------------------
    # آخرین ID
    # -----------------------------------------------------

    current_last_id = int(
        channel_state.get(
            "last_id",
            0
        )
    )

    if post_id > current_last_id:
        channel_state["last_id"] = post_id

    # -----------------------------------------------------
    # محدود کردن State
    # -----------------------------------------------------

    if len(processed_ids) > MAX_PROCESSED_IDS:
        del processed_ids[
            :-MAX_PROCESSED_IDS
        ]

    if len(fingerprints) > MAX_FINGERPRINTS:
        del fingerprints[
            :-MAX_FINGERPRINTS
        ]


# =========================================================
# SEND POST
# =========================================================

def send_post(
    post,
    username
):
    post_id = post["id"]

    text = (
        post.get("text") or ""
    ).strip()

    link = post["link"]

    photos = post.get(
        "photos",
        []
    )

    video = post.get(
        "video"
    )

    # -----------------------------------------------------
    # FILTER
    # -----------------------------------------------------

    filtered, matched_pattern = (
        contains_filtered_content(
            text
        )
    )

    if filtered:

        print("")
        print(
            f"[FILTERED] @{username} "
            f"post={post_id}"
        )

        print(
            "[FILTERED] "
            "پست به دلیل وجود عبارت ممنوع "
            "ارسال نشد."
        )

        print(
            f"[FILTERED] pattern={matched_pattern}"
        )

        # نکته مهم:
        # اینجا True برمی‌گردانیم تا پست
        # به عنوان handled ثبت شود.
        return True, "filtered"

    # -----------------------------------------------------
    # LOG
    # -----------------------------------------------------

    print(
        f"[SEND] @{username} "
        f"post={post_id} "
        f"photos={len(photos)} "
        f"video={bool(video)}"
    )

    # -----------------------------------------------------
    # CAPTION
    # -----------------------------------------------------

    if text:

        caption = (
            f"📢 @{username}\n\n"
            f"{text}\n\n"
            f"🔗 {link}"
        )

    else:

        caption = (
            f"📢 @{username}\n\n"
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

            return True, "sent"

        except TelegramAPIError as e:

            print(
                f"[ERROR] ارسال متن "
                f"پست {post_id}: {e}"
            )

            return False, "failed"

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
                    f"{index + 1}/"
                    f"{len(photos)}"
                )

                send_photo(
                    photo_url,
                    photo_caption
                )

                success = True

                print(
                    "[OK] عکس ارسال شد."
                )

            except TelegramAPIError as e:

                print(
                    "[WARN] ارسال مستقیم "
                    f"عکس ناموفق بود: {e}"
                )

                # -----------------------------------------
                # FALLBACK DOWNLOAD
                # -----------------------------------------

                try:

                    local_file = (
                        download_file(
                            photo_url
                        )
                    )

                    try:

                        send_document_file(
                            local_file,
                            photo_caption
                        )

                        success = True

                        print(
                            "[OK] عکس با "
                            "آپلود مستقیم "
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
                        "[ERROR] تلاش دوم "
                        f"عکس ناموفق بود: {e2}"
                    )

        if success:
            return True, "sent"

        return False, "failed"

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

            return True, "sent"

        except TelegramAPIError as e:

            print(
                "[WARN] ارسال ویدیو "
                f"ناموفق بود: {e}"
            )

            # ------------------------------------------------
            # دانلود و آپلود به عنوان Document
            # ------------------------------------------------

            try:

                local_file = download_file(
                    video
                )

                try:

                    send_document_file(
                        local_file,
                        caption
                    )

                    print(
                        "[OK] ویدیو با "
                        "آپلود مستقیم "
                        "ارسال شد."
                    )

                    return True, "sent"

                finally:

                    try:
                        os.remove(
                            local_file
                        )
                    except Exception:
                        pass

            except Exception as e2:

                print(
                    "[WARN] آپلود مستقیم "
                    f"ویدیو هم ناموفق بود: {e2}"
                )

                # ------------------------------------------------
                # آخرین fallback: ارسال لینک
                # ------------------------------------------------

                try:

                    send_message(
                        f"🎬 پست جدید از "
                        f"@{username}\n\n"
                        f"{text}\n\n"
                        f"🔗 {link}\n\n"
                        f"⚠️ ارسال مستقیم ویدیو "
                        f"به دلیل محدودیت Telegram "
                        f"ناموفق بود."
                    )

                    print(
                        "[OK] لینک ویدیو "
                        "ارسال شد."
                    )

                    return True, "link_fallback"

                except Exception as e3:

                    print(
                        "[ERROR] ارسال لینک "
                        f"هم شکست خورد: {e3}"
                    )

                    return False, "failed"

    return False, "failed"


# =========================================================
# BOT COMMANDS
# =========================================================

HELP_TEXT = (
    "🤖 ربات ارسال پست\n\n"
    "/add username - افزودن کانال\n"
    "/remove username - حذف کانال\n"
    "/list - لیست کانال‌ها\n"
    "/id - نمایش شناسه چت فعلی\n"
    "/help - راهنما"
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
# HANDLE UPDATES
# =========================================================

def handle_updates(
    channels,
    bot_state
):

    offset = (
        int(
            bot_state.get(
                "last_update_id",
                0
            )
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

        bot_state["last_update_id"] = (
            update["update_id"]
        )

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
            message.get("text") or ""
        ).strip()

        if not text:
            continue

        # فقط مالک
        if user_id != OWNER_ID:
            continue

        parts = text.split(
            maxsplit=1
        )

        command = (
            parts[0]
            .lower()
        )

        argument = (
            parts[1].strip()
            if len(parts) > 1
            else ""
        )

        # -------------------------------------------------
        # /id
        # -------------------------------------------------

        if command == "/id":

            send_message_to_chat(
                chat_id,
                (
                    f"🆔 Chat ID:\n"
                    f"{chat_id}"
                )
            )

        # -------------------------------------------------
        # /start /help /manage
        # -------------------------------------------------

        elif command in (
            "/start",
            "/help",
            "/manage"
        ):

            send_message_to_chat(
                chat_id,
                HELP_TEXT
            )

        # -------------------------------------------------
        # /add
        # -------------------------------------------------

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
                    (
                        "مثال:\n"
                        "/add akhbarfars"
                    )
                )

                continue

            existing = [
                c.lower().lstrip("@")
                for c in channels
            ]

            if username in existing:

                send_message_to_chat(
                    chat_id,
                    (
                        f"⚠️ @{username} "
                        f"قبلاً اضافه شده."
                    )
                )

                continue

            channels.append(
                username
            )

            send_message_to_chat(
                chat_id,
                (
                    f"✅ @{username} "
                    f"اضافه شد."
                )
            )

        # -------------------------------------------------
        # /remove
        # -------------------------------------------------

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
                    (
                        f"🗑 @{username} "
                        f"حذف شد."
                    )
                )

            else:

                send_message_to_chat(
                    chat_id,
                    (
                        f"❌ @{username} "
                        f"پیدا نشد."
                    )
                )

        # -------------------------------------------------
        # /list
        # -------------------------------------------------

        elif command == "/list":

            if not channels:

                send_message_to_chat(
                    chat_id,
                    (
                        "📋 لیست کانال‌ها "
                        "خالی است."
                    )
                )

            else:

                send_message_to_chat(
                    chat_id,
                    (
                        "📋 کانال‌های فعال:\n\n"
                        +
                        "\n".join(
                            f"• @{c}"
                            for c in channels
                        )
                    )
                )

        # -------------------------------------------------
        # UNKNOWN
        # -------------------------------------------------

        else:

            send_message_to_chat(
                chat_id,
                (
                    "❌ دستور ناشناخته است.\n\n"
                    + HELP_TEXT
                )
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
            .lower()
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
                f"[ERROR] دریافت "
                f"@{username}: {e}"
            )

            continue

        print(
            f"[FOUND] {len(posts)} "
            f"پست در صفحه"
        )

        if not posts:
            continue

        # -------------------------------------------------
        # CHANNEL STATE
        # -------------------------------------------------

        if username not in state:

            state[username] = (
                normalize_channel_state(
                    {}
                )
            )

        channel_state = (
            normalize_channel_state(
                state[username]
            )
        )

        state[username] = channel_state

        # -------------------------------------------------
        # FIRST RUN
        # -------------------------------------------------

        if channel_state["last_id"] == 0:

            latest_post = posts[-1]

            channel_state["last_id"] = (
                latest_post["id"]
            )

            # آخرین پست را فقط به عنوان baseline
            # ثبت می‌کنیم و ارسال نمی‌کنیم.
            channel_state.setdefault(
                "processed_ids",
                []
            )

            channel_state.setdefault(
                "fingerprints",
                []
            )

            if latest_post["id"] not in (
                channel_state[
                    "processed_ids"
                ]
            ):
                channel_state[
                    "processed_ids"
                ].append(
                    latest_post["id"]
                )

            fingerprint = (
                create_content_fingerprint(
                    latest_post
                )
            )

            if fingerprint not in (
                channel_state[
                    "fingerprints"
                ]
            ):
                channel_state[
                    "fingerprints"
                ].append(
                    fingerprint
                )

            print(
                f"[INIT] @{username} "
                f"baseline="
                f"{latest_post['id']}"
            )

            continue

        # -------------------------------------------------
        # NEW POSTS
        # -------------------------------------------------

        new_posts = []

        for post in posts:

            duplicate, reason = (
                is_duplicate_post(
                    post,
                    channel_state
                )
            )

            if duplicate:

                print(
                    f"[DUPLICATE] "
                    f"@{username} "
                    f"post={post['id']} "
                    f"reason={reason}"
                )

                continue

            new_posts.append(
                post
            )

        if not new_posts:

            print(
                "[INFO] پست جدیدی "
                "نیست."
            )

            continue

        print(
            f"[NEW] {len(new_posts)} "
            f"پست جدید"
        )

        # -------------------------------------------------
        # PROCESS EACH POST
        # -------------------------------------------------

        for post in new_posts:

            post_id = post["id"]

            print("")
            print(
                f"[PROCESS] @{username} "
                f"post={post_id}"
            )

            try:

                success, result_type = (
                    send_post(
                        post,
                        username
                    )
                )

            except Exception as e:

                print(
                    f"[ERROR] پردازش "
                    f"@{username} "
                    f"post={post_id}: {e}"
                )

                success = False
                result_type = "failed"

            # -------------------------------------------------
            # SUCCESS / FILTERED
            # -------------------------------------------------

            if success:

                mark_post_processed(
                    channel_state,
                    post
                )

                print(
                    f"[STATE] @{username} "
                    f"post={post_id} "
                    f"handled={result_type}"
                )

                # مهم:
                # بعد از هر پست State را ذخیره می‌کنیم
                # تا اگر اجرای GitHub وسط کار قطع شد،
                # پست‌های قبلی دوباره ارسال نشوند.
                #
                # توجه:
                # save_json در main هم دوباره اجرا می‌شود.
                #
                # اینجا state مستقیماً روی دیسک ذخیره می‌شود.
                #
                # چون check_channels فقط state را دارد،
                # ذخیره در همین مرحله ضروری است.

                save_json(
                    STATE_FILE,
                    state
                )

                time.sleep(
                    SEND_DELAY
                )

            # -------------------------------------------------
            # FAILED
            # -------------------------------------------------

            else:

                print(
                    f"[FAILED] @{username} "
                    f"post={post_id}"
                )

                print(
                    "[STATE] این پست "
                    "ثبت نشد و اجرای بعدی "
                    "دوباره تلاش می‌کند."
                )

                # اگر یک پست fail شد،
                # پست‌های بعدی را فعلاً نمی‌فرستیم
                # تا ترتیب حفظ شود.
                break

    return state


# =========================================================
# MAIN
# =========================================================

def main():

    global CURRENT_CHAT_ID

    print("")
    print("=" * 60)
    print(
        "TELEGRAM PUBLIC CHANNEL "
        "FORWARDER"
    )
    print("=" * 60)

    # -----------------------------------------------------
    # LOAD FILES
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

    # -----------------------------------------------------
    # NORMALIZE
    # -----------------------------------------------------

    state = normalize_full_state(
        state
    )

    if not isinstance(
        bot_state,
        dict
    ):
        bot_state = {
            "last_update_id": 0
        }

    # -----------------------------------------------------
    # DESTINATION
    # -----------------------------------------------------

    CURRENT_CHAT_ID = (
        get_current_chat_id(
            bot_state
        )
    )

    print(
        f"[INFO] تعداد کانال‌ها: "
        f"{len(channels)}"
    )

    print(
        f"[INFO] مقصد فعلی: "
        f"{CURRENT_CHAT_ID}"
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
    # SAVE POSSIBLY UPDATED CHAT ID
    # -----------------------------------------------------

    bot_state[
        "destination_chat_id"
    ] = CURRENT_CHAT_ID

    # -----------------------------------------------------
    # HANDLE COMMANDS
    # -----------------------------------------------------

    channels, bot_state = (
        handle_updates(
            channels,
            bot_state
        )
    )

    # -----------------------------------------------------
    # CHECK CHANNELS
    # -----------------------------------------------------

    state = check_channels(
        channels,
        state
    )

    # -----------------------------------------------------
    # SAVE EVERYTHING
    # -----------------------------------------------------

    bot_state[
        "destination_chat_id"
    ] = CURRENT_CHAT_ID

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

    # -----------------------------------------------------
    # FINISH
    # -----------------------------------------------------

    print("")
    print("=" * 60)
    print(
        f"[FINAL CHAT ID] "
        f"{CURRENT_CHAT_ID}"
    )
    print(
        "[DONE] اجرای برنامه تمام شد."
    )
    print("=" * 60)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
