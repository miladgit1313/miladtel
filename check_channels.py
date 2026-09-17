import os
import json
import time
import re
import hashlib
from difflib import SequenceMatcher
from datetime import datetime, timezone

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

REQUEST_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 180

SEND_DELAY = 2

# حداکثر تعداد پست‌های قبلی که برای ضدتکرار نگه می‌داریم
MAX_PROCESSED_IDS = 1000

# تاریخچه ضدتکرار بین کانال‌ها
MAX_GLOBAL_HISTORY = 1000

# حداقل طول متن برای تشخیص شباهت تقریبی
MIN_FUZZY_TEXT_LENGTH = 60

# آستانه شباهت متنی
FUZZY_SIMILARITY_THRESHOLD = 0.88

# آستانه شباهت کلمات
TOKEN_SIMILARITY_THRESHOLD = 0.80


# =========================================================
# HEADERS
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

FILTER_PATTERNS = [
    r"شرط[\s\u200c\u200d_ـ\-]*بندی",
    r"وین[\s\u200c\u200d_ـ\-]*تو[\s\u200c\u200d_ـ\-]*بت",
    r"وان[\s\u200c\u200d_ـ\-]*ایکس",
    r"1[\s\u200c\u200d_ـ\-._]*x[\s\u200c\u200d_ـ\-._]*bet",
]


def normalize_text(text):
    if not text:
        return ""

    text = str(text)

    text = text.replace("ي", "ی")
    text = text.replace("ى", "ی")
    text = text.replace("ك", "ک")

    text = text.replace("\u200c", " ")
    text = text.replace("\u200d", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\u2060", "")

    text = re.sub(r"\s+", " ", text)

    return text.strip().lower()


def normalize_for_similarity(text):
    """
    نرمال‌سازی مخصوص تشخیص پست‌های مشابه.

    لینک‌ها و usernameها حذف می‌شوند تا مثلاً:

    @channelA
    https://t.me/...
    
    باعث شوند دو پست مشابه، متفاوت تشخیص داده نشوند.
    """

    text = normalize_text(text)

    # حذف URL
    text = re.sub(
        r"https?://\S+|www\.\S+",
        " ",
        text
    )

    # حذف @username
    text = re.sub(
        r"@\w+",
        " ",
        text
    )

    # حذف هشتگ از نظر علامت # ولی متن هشتگ باقی می‌ماند
    text = text.replace("#", " ")

    # حذف کاراکترهای تزئینی
    text = re.sub(
        r"[^\w\s\u0600-\u06FF]",
        " ",
        text,
        flags=re.UNICODE
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def contains_filtered_content(text):
    normalized = normalize_text(text)

    if not normalized:
        return False, None

    for pattern in FILTER_PATTERNS:
        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE
        ):
            return True, pattern

    return False, None


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
    temp_path = f"{path}.tmp"

    try:
        with open(
            temp_path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_path,
            path
        )

    except Exception as e:
        print(
            f"[ERROR] ذخیره {path}: {e}"
        )


# =========================================================
# STATE
# =========================================================

def empty_channel_state():
    return {
        "last_id": 0,
        "processed_ids": []
    }


def empty_global_state():
    return {
        "history": []
    }


def normalize_channel_state(value):
    if isinstance(value, dict):

        try:
            last_id = int(
                value.get(
                    "last_id",
                    0
                )
            )
        except Exception:
            last_id = 0

        processed_ids = value.get(
            "processed_ids",
            []
        )

        if not isinstance(
            processed_ids,
            list
        ):
            processed_ids = []

        clean_ids = []

        for item in processed_ids:
            try:
                clean_ids.append(
                    int(item)
                )
            except Exception:
                pass

        return {
            "last_id": last_id,
            "processed_ids": clean_ids[
                -MAX_PROCESSED_IDS:
            ]
        }

    # پشتیبانی از state قدیمی:
    # "channel": 123
    try:
        old_id = int(value)
    except Exception:
        old_id = 0

    return {
        "last_id": old_id,
        "processed_ids": []
    }


def normalize_state(raw_state):
    """
    تبدیل stateهای قدیمی و جدید به ساختار جدید.

    ساختار جدید:

    {
        "channels": {
            "channel1": {
                "last_id": 123,
                "processed_ids": []
            }
        },
        "global": {
            "history": []
        }
    }
    """

    # اگر قبلاً نسخه جدید است
    if (
        isinstance(raw_state, dict)
        and "channels" in raw_state
    ):

        channels_raw = raw_state.get(
            "channels",
            {}
        )

        global_raw = raw_state.get(
            "global",
            {}
        )

        channels = {}

        if isinstance(
            channels_raw,
            dict
        ):
            for username, value in channels_raw.items():
                channels[
                    username
                ] = normalize_channel_state(
                    value
                )

        history = []

        if isinstance(
            global_raw,
            dict
        ):
            history = global_raw.get(
                "history",
                []
            )

        if not isinstance(
            history,
            list
        ):
            history = []

        return {
            "channels": channels,
            "global": {
                "history": history[
                    -MAX_GLOBAL_HISTORY:
                ]
            }
        }

    # -----------------------------------------------------
    # مهاجرت State قدیمی
    # -----------------------------------------------------

    channels = {}

    if isinstance(
        raw_state,
        dict
    ):

        for username, value in raw_state.items():

            if username in (
                "global",
                "channels"
            ):
                continue

            channels[
                username
            ] = normalize_channel_state(
                value
            )

    return {
        "channels": channels,
        "global": {
            "history": []
        }
    }


# =========================================================
# DESTINATION CHAT
# =========================================================

CURRENT_CHAT_ID = ENV_CHAT_ID


def get_current_chat_id(bot_state):
    saved_id = bot_state.get(
        "destination_chat_id"
    )

    if saved_id:
        return str(
            saved_id
        ).strip()

    return ENV_CHAT_ID


def update_destination_chat_id(
    new_chat_id
):
    global CURRENT_CHAT_ID

    new_chat_id = str(
        new_chat_id
    ).strip()

    if not new_chat_id:
        return

    if (
        CURRENT_CHAT_ID
        != new_chat_id
    ):

        print("")
        print(
            "=" * 60
        )
        print(
            "[MIGRATION DETECTED]"
        )
        print(
            f"[OLD CHAT ID] "
            f"{CURRENT_CHAT_ID}"
        )
        print(
            f"[NEW CHAT ID] "
            f"{new_chat_id}"
        )
        print(
            "[INFO] گروه به Supergroup "
            "منتقل شده است."
        )
        print(
            "=" * 60
        )

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

        super().__init__(
            f"Telegram API error "
            f"{error_code}: "
            f"{description}"
        )


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_call(
    method,
    destination=False,
    retry_migration=True,
    **params
):

    if destination:
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
    # AUTO SUPERGROUP MIGRATION
    # -----------------------------------------------------

    if (
        destination
        and migrate_to
        and retry_migration
    ):

        update_destination_chat_id(
            migrate_to
        )

        return telegram_call(
            method,
            destination=True,
            retry_migration=False,
            **{
                k: v
                for k, v in params.items()
                if k != "chat_id"
            }
        )

    raise TelegramAPIError(
        error_code,
        description,
        parameters_info
    )


# =========================================================
# MULTIPART
# =========================================================

def telegram_multipart_call(
    method,
    data=None,
    files=None,
    retry_migration=True
):

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

    if (
        migrate_to
        and retry_migration
    ):

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
# DESTINATION TEST
# =========================================================

def test_destination():

    print("")
    print(
        "=" * 60
    )
    print(
        "TESTING DESTINATION CHAT"
    )
    print(
        "=" * 60
    )

    print(
        f"[INFO] CHAT_ID = "
        f"{CURRENT_CHAT_ID}"
    )

    try:

        result = telegram_call(
            "getChat",
            destination=True
        )

        chat = result.get(
            "result",
            {}
        )

        actual_id = chat.get(
            "id"
        )

        if actual_id:
            update_destination_chat_id(
                actual_id
            )

        print("")
        print(
            "[OK] مقصد پیدا شد."
        )

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

        if chat.get(
            "username"
        ):
            print(
                f"[CHAT USERNAME] "
                f"@{chat.get('username')}"
            )

        print(
            "=" * 60
        )

        return True

    except TelegramAPIError as e:

        print("")
        print(
            "[FATAL] مقصد Telegram مشکل دارد."
        )

        print(
            f"[DETAIL] {e}"
        )

        print(
            "=" * 60
        )

        return False


# =========================================================
# SEND FUNCTIONS
# =========================================================

def send_message(text):

    return telegram_call(
        "sendMessage",
        destination=True,
        text=text[:4096],
        disable_web_page_preview=False
    )


def send_photo(
    photo_url,
    caption=""
):

    return telegram_call(
        "sendPhoto",
        destination=True,
        photo=photo_url,
        caption=caption[:1024]
    )


def send_video(
    video_url,
    caption=""
):

    return telegram_call(
        "sendVideo",
        destination=True,
        video=video_url,
        caption=caption[:1024],
        supports_streaming=True
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
# DOWNLOAD
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

    filename = re.sub(
        r"[^a-zA-Z0-9._-]",
        "_",
        filename
    )

    path = (
        f"/tmp/"
        f"tg_media_"
        f"{int(time.time() * 1000)}_"
        f"{filename}"
    )

    with open(
        path,
        "wb"
    ) as f:
        f.write(
            response.content
        )

    print(
        f"[DOWNLOAD OK] -> {path}"
    )

    return path


# =========================================================
# DOCUMENT
# =========================================================

def send_document_file(
    file_path,
    caption=""
):

    with open(
        file_path,
        "rb"
    ) as file:

        return telegram_multipart_call(
            "sendDocument",
            data={
                "caption": caption[:1024]
            },
            files={
                "document": file
            }
        )


# =========================================================
# FETCH POSTS
# =========================================================

def fetch_channel_posts(
    username
):

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
        # PUBLISHED TIME
        # -------------------------------------------------

        published_at = ""

        time_tag = wrap.select_one(
            ".tgme_widget_message_date time"
        )

        if time_tag:

            published_at = (
                time_tag.get(
                    "datetime",
                    ""
                )
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
                "video": video_url,
                "published_at": published_at
            }
        )

    posts.sort(
        key=lambda x: x["id"]
    )

    return posts


# =========================================================
# MEDIA FINGERPRINT
# =========================================================

def media_fingerprint(post):

    parts = []

    for photo in post.get(
        "photos",
        []
    ):

        parts.append(
            "photo:"
            + str(photo).strip()
        )

    video = post.get(
        "video"
    )

    if video:

        parts.append(
            "video:"
            + str(video).strip()
        )

    if not parts:
        return ""

    raw = "|".join(
        sorted(parts)
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()


# =========================================================
# CONTENT FINGERPRINT
# =========================================================

def content_fingerprint(
    post
):

    text = normalize_for_similarity(
        post.get(
            "text",
            ""
        )
    )

    media_fp = media_fingerprint(
        post
    )

    raw = (
        text
        + "||"
        + media_fp
    )

    if not raw.strip():

        raw = str(
            post.get(
                "id",
                ""
            )
        )

    return hashlib.sha256(
        raw.encode(
            "utf-8",
            errors="ignore"
        ).hexdigest().encode()
    ).hexdigest()


# =========================================================
# TEXT SIMILARITY
# =========================================================

def token_similarity(
    text1,
    text2
):

    words1 = set(
        normalize_for_similarity(
            text1
        ).split()
    )

    words2 = set(
        normalize_for_similarity(
            text2
        ).split()
    )

    if not words1 or not words2:
        return 0.0

    intersection = len(
        words1 & words2
    )

    union = len(
        words1 | words2
    )

    if union == 0:
        return 0.0

    return intersection / union


def text_similarity(
    text1,
    text2
):

    a = normalize_for_similarity(
        text1
    )

    b = normalize_for_similarity(
        text2
    )

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if (
        len(a) < MIN_FUZZY_TEXT_LENGTH
        or
        len(b) < MIN_FUZZY_TEXT_LENGTH
    ):
        return 0.0

    sequence_score = (
        SequenceMatcher(
            None,
            a,
            b
        ).ratio()
    )

    token_score = token_similarity(
        a,
        b
    )

    # برای متن‌های طولانی،
    # هر دو معیار را در نظر می‌گیریم.
    return max(
        sequence_score,
        token_score
    )


# =========================================================
# GLOBAL DUPLICATE DETECTION
# =========================================================

def find_global_duplicate(
    post,
    global_state
):

    history = global_state.get(
        "history",
        []
    )

    current_text = post.get(
        "text",
        ""
    )

    current_fp = content_fingerprint(
        post
    )

    current_media_fp = media_fingerprint(
        post
    )

    # -----------------------------------------------------
    # Exact fingerprint
    # -----------------------------------------------------

    for item in reversed(history):

        if item.get(
            "fingerprint"
        ) == current_fp:

            return item, "exact fingerprint"

        # -------------------------------------------------
        # Media exact match
        # -------------------------------------------------

        if (
            current_media_fp
            and
            item.get(
                "media_fingerprint"
            )
            == current_media_fp
        ):

            old_text = item.get(
                "text",
                ""
            )

            # اگر رسانه یکی باشد و متن خالی باشد
            # یا متن‌ها هم شباهت داشته باشند.
            if (
                not current_text.strip()
                or
                not old_text.strip()
                or
                text_similarity(
                    current_text,
                    old_text
                ) >= 0.70
            ):

                return item, "same media"

    # -----------------------------------------------------
    # Fuzzy text match
    # -----------------------------------------------------

    if current_text.strip():

        for item in reversed(history):

            old_text = item.get(
                "text",
                ""
            )

            if not old_text.strip():
                continue

            score = text_similarity(
                current_text,
                old_text
            )

            if (
                score
                >= FUZZY_SIMILARITY_THRESHOLD
            ):

                return item, (
                    f"similar text "
                    f"{score:.2f}"
                )

    return None, None


# =========================================================
# MESSAGE CAPTION
# =========================================================

def build_message_text(
    username,
    text,
    link,
    sources=None
):

    sources = sources or []

    if text:

        result = (
            f"📢 @{username}\n\n"
            f"{text}\n\n"
            f"🔗 {link}"
        )

    else:

        result = (
            f"📢 @{username}\n\n"
            f"🔗 {link}"
        )

    if sources:

        unique_sources = []

        for source in sources:

            if source not in unique_sources:

                unique_sources.append(
                    source
                )

        result += (
            "\n\n"
            "📚 منابع مشابه:\n"
            +
            "\n".join(
                f"• @{source}"
                for source in unique_sources
            )
        )

    return result


# =========================================================
# EDIT ORIGINAL MESSAGE WITH NEW SOURCE
# =========================================================

def add_duplicate_source(
    history_item,
    duplicate_username
):

    sources = history_item.setdefault(
        "sources",
        []
    )

    if (
        duplicate_username
        not in sources
    ):

        sources.append(
            duplicate_username
        )

    message_id = history_item.get(
        "message_id"
    )

    message_kind = history_item.get(
        "message_kind"
    )

    original_username = (
        history_item.get(
            "original_username",
            ""
        )
    )

    original_text = (
        history_item.get(
            "original_text",
            ""
        )
    )

    original_link = (
        history_item.get(
            "original_link",
            ""
        )
    )

    if not message_id:
        return False

    new_text = build_message_text(
        original_username,
        original_text,
        original_link,
        sources
    )

    try:

        if message_kind == "text":

            telegram_call(
                "editMessageText",
                destination=True,
                message_id=message_id,
                text=new_text[:4096],
                disable_web_page_preview=False
            )

        else:

            telegram_call(
                "editMessageCaption",
                destination=True,
                message_id=message_id,
                caption=new_text[:1024]
            )

        print(
            f"[SOURCE UPDATED] "
            f"+@{duplicate_username}"
        )

        return True

    except Exception as e:

        print(
            "[WARN] اضافه کردن منبع "
            f"@{duplicate_username} "
            f"ناموفق بود: {e}"
        )

        return False


# =========================================================
# MARK GLOBAL SENT
# =========================================================

def add_global_history(
    global_state,
    post,
    username,
    message_result,
    message_kind
):

    history = global_state.setdefault(
        "history",
        []
    )

    message = {}

    if isinstance(
        message_result,
        dict
    ):

        message = message_result.get(
            "result",
            {}
        )

    message_id = message.get(
        "message_id"
    )

    item = {
        "fingerprint": content_fingerprint(
            post
        ),
        "media_fingerprint": media_fingerprint(
            post
        ),
        "text": post.get(
            "text",
            ""
        ),
        "normalized_text": normalize_for_similarity(
            post.get(
                "text",
                ""
            )
        ),
        "original_username": username,
        "original_text": post.get(
            "text",
            ""
        ),
        "original_link": post.get(
            "link",
            ""
        ),
        "post_id": post.get(
            "id"
        ),
        "published_at": post.get(
            "published_at",
            ""
        ),
        "message_id": message_id,
        "message_kind": message_kind,
        "sources": [
            username
        ],
        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    history.append(
        item
    )

    if len(history) > MAX_GLOBAL_HISTORY:

        del history[
            :-MAX_GLOBAL_HISTORY
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
        post.get(
            "text"
        ) or ""
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
    # FILTER FIRST
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
            f"[FILTERED] pattern="
            f"{matched_pattern}"
        )

        return {
            "success": True,
            "type": "filtered",
            "result": None,
            "message_kind": None
        }

    # -----------------------------------------------------
    # CAPTION
    # -----------------------------------------------------

    caption = build_message_text(
        username,
        text,
        link
    )

    print(
        f"[SEND] @{username} "
        f"post={post_id} "
        f"photos={len(photos)} "
        f"video={bool(video)}"
    )

    # =====================================================
    # TEXT
    # =====================================================

    if (
        not photos
        and
        not video
    ):

        try:

            result = send_message(
                caption
            )

            print(
                "[OK] متن پست ارسال شد."
            )

            return {
                "success": True,
                "type": "sent",
                "result": result,
                "message_kind": "text"
            }

        except Exception as e:

            print(
                f"[ERROR] متن: {e}"
            )

            return {
                "success": False,
                "type": "failed",
                "result": None,
                "message_kind": None
            }

    # =====================================================
    # PHOTO
    # =====================================================

    if photos:

        first_result = None
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

                result = send_photo(
                    photo_url,
                    photo_caption
                )

                if index == 0:

                    first_result = result

                success_count += 1

                print(
                    f"[OK] عکس "
                    f"{index + 1}/"
                    f"{len(photos)} ارسال شد."
                )

            except Exception as e:

                print(
                    f"[WARN] عکس "
                    f"{index + 1} "
                    f"ارسال مستقیم نشد: {e}"
                )

                try:

                    local_file = download_file(
                        photo_url
                    )

                    try:

                        result = send_document_file(
                            local_file,
                            photo_caption
                        )

                        if index == 0:

                            first_result = result

                        success_count += 1

                        print(
                            "[OK] عکس با "
                            "آپلود مستقیم ارسال شد."
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
                        f"[ERROR] عکس "
                        f"{index + 1}: "
                        f"{e2}"
                    )

        if success_count > 0:

            return {
                "success": True,
                "type": "sent",
                "result": first_result,
                "message_kind": "caption"
            }

        return {
            "success": False,
            "type": "failed",
            "result": None,
            "message_kind": None
        }

    # =====================================================
    # VIDEO
    # =====================================================

    if video:

        try:

            result = send_video(
                video,
                caption
            )

            print(
                "[OK] ویدیو ارسال شد."
            )

            return {
                "success": True,
                "type": "sent",
                "result": result,
                "message_kind": "caption"
            }

        except Exception as e:

            print(
                f"[WARN] ویدیو مستقیم "
                f"ارسال نشد: {e}"
            )

        # -------------------------------------------------
        # VIDEO DOWNLOAD
        # -------------------------------------------------

        try:

            local_file = download_file(
                video
            )

            try:

                result = send_document_file(
                    local_file,
                    caption
                )

                print(
                    "[OK] ویدیو به صورت "
                    "Document ارسال شد."
                )

                return {
                    "success": True,
                    "type": "sent",
                    "result": result,
                    "message_kind": "caption"
                }

            finally:

                try:
                    os.remove(
                        local_file
                    )
                except Exception:
                    pass

        except Exception as e2:

            print(
                f"[WARN] آپلود ویدیو "
                f"ناموفق بود: {e2}"
            )

        # -------------------------------------------------
        # FINAL LINK FALLBACK
        # -------------------------------------------------

        try:

            result = send_message(
                (
                    f"🎬 پست جدید از "
                    f"@{username}\n\n"
                    f"{text}\n\n"
                    f"🔗 {link}\n\n"
                    f"⚠️ ارسال مستقیم ویدیو "
                    f"به دلیل محدودیت حجم "
                    f"ناموفق بود."
                )
            )

            print(
                "[OK] لینک ویدیو ارسال شد."
            )

            return {
                "success": True,
                "type": "link_fallback",
                "result": result,
                "message_kind": "text"
            }

        except Exception as e3:

            print(
                f"[ERROR] لینک ویدیو: "
                f"{e3}"
            )

            return {
                "success": False,
                "type": "failed",
                "result": None,
                "message_kind": None
            }

    return {
        "success": False,
        "type": "failed",
        "result": None,
        "message_kind": None
    }


# =========================================================
# COMMANDS
# =========================================================

HELP_TEXT = (
    "🤖 ربات ارسال پست\n\n"
    "/add username - افزودن کانال\n"
    "/remove username - حذف کانال\n"
    "/list - لیست کانال‌ها\n"
    "/id - نمایش شناسه چت فعلی\n"
    "/help - راهنما"
)


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

        bot_state[
            "last_update_id"
        ] = update[
            "update_id"
        ]

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
            message.get(
                "text"
            ) or ""
        ).strip()

        if not text:
            continue

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
        # HELP
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
        # ADD
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
        # REMOVE
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
        # LIST
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
# PUBLISHED TIME SORT
# =========================================================

def published_timestamp(
    post
):

    value = post.get(
        "published_at",
        ""
    )

    if not value:
        return 0.0

    try:

        text = value

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        dt = datetime.fromisoformat(
            text
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.timestamp()

    except Exception:

        return 0.0


# =========================================================
# CHECK ALL CHANNELS
# =========================================================

def check_channels(
    channels,
    state
):

    channel_states = state.setdefault(
        "channels",
        {}
    )

    global_state = state.setdefault(
        "global",
        {}
    )

    global_state.setdefault(
        "history",
        []
    )

    candidates = []

    # =====================================================
    # FIRST: FETCH ALL CHANNELS
    # =====================================================

    for channel_index, username in enumerate(
        channels
    ):

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

        if username not in channel_states:

            channel_states[
                username
            ] = empty_channel_state()

        channel_state = normalize_channel_state(
            channel_states[
                username
            ]
        )

        channel_states[
            username
        ] = channel_state

        # -------------------------------------------------
        # FIRST RUN
        # -------------------------------------------------

        if channel_state["last_id"] == 0:

            latest = posts[-1]

            channel_state[
                "last_id"
            ] = latest["id"]

            channel_state.setdefault(
                "processed_ids",
                []
            )

            channel_state[
                "processed_ids"
            ].append(
                latest["id"]
            )

            print(
                f"[INIT] @{username} "
                f"baseline={latest['id']}"
            )

            continue

        # -------------------------------------------------
        # FIND NEW POSTS
        # -------------------------------------------------

        for post in posts:

            post_id = int(
                post["id"]
            )

            last_id = int(
                channel_state[
                    "last_id"
                ]
            )

            processed_ids = (
                channel_state[
                    "processed_ids"
                ]
            )

            if post_id <= last_id:
                continue

            if post_id in processed_ids:
                continue

            candidates.append(
                {
                    "username": username,
                    "channel_index": channel_index,
                    "post": post
                }
            )

    # =====================================================
    # SORT ALL NEW POSTS BY PUBLICATION TIME
    # =====================================================

    candidates.sort(
        key=lambda item: (
            published_timestamp(
                item["post"]
            ),
            item["channel_index"],
            item["post"]["id"]
        )
    )

    print("")
    print(
        "=" * 60
    )

    print(
        f"[GLOBAL] تعداد پست‌های جدید: "
        f"{len(candidates)}"
    )

    print(
        "=" * 60
    )

    # =====================================================
    # PROCESS
    # =====================================================

    for item in candidates:

        username = item[
            "username"
        ]

        post = item[
            "post"
        ]

        post_id = post[
            "id"
        ]

        channel_state = channel_states[
            username
        ]

        print("")
        print(
            "=" * 60
        )

        print(
            f"[PROCESS] @{username} "
            f"post={post_id}"
        )

        # -------------------------------------------------
        # FILTER
        # -------------------------------------------------

        filtered, matched = (
            contains_filtered_content(
                post.get(
                    "text",
                    ""
                )
            )
        )

        if filtered:

            print(
                f"[FILTERED] @{username} "
                f"post={post_id}"
            )

            print(
                f"[FILTERED] pattern={matched}"
            )

            # پست فیلتر شده را processed می‌کنیم
            # ولی وارد global history نمی‌کنیم.
            channel_state[
                "processed_ids"
            ].append(
                post_id
            )

            channel_state[
                "last_id"
            ] = max(
                int(
                    channel_state[
                        "last_id"
                    ]
                ),
                post_id
            )

            if len(
                channel_state[
                    "processed_ids"
                ]
            ) > MAX_PROCESSED_IDS:

                channel_state[
                    "processed_ids"
                ] = channel_state[
                    "processed_ids"
                ][
                    -MAX_PROCESSED_IDS:
                ]

            save_json(
                STATE_FILE,
                state
            )

            continue

        # -------------------------------------------------
        # GLOBAL DUPLICATE
        # -------------------------------------------------

        duplicate_item, reason = (
            find_global_duplicate(
                post,
                global_state
            )
        )

        if duplicate_item:

            print(
                f"[GLOBAL DUPLICATE] "
                f"@{username} "
                f"post={post_id}"
            )

            print(
                f"[GLOBAL DUPLICATE] "
                f"reason={reason}"
            )

            original_source = (
                duplicate_item.get(
                    "original_username",
                    "unknown"
                )
            )

            print(
                f"[GLOBAL DUPLICATE] "
                f"نسخه اصلی: "
                f"@{original_source}"
            )

            # -------------------------------------------------
            # اضافه کردن منبع جدید
            # -------------------------------------------------

            add_duplicate_source(
                duplicate_item,
                username
            )

            # -------------------------------------------------
            # ثبت processed در کانال فعلی
            # -------------------------------------------------

            channel_state[
                "processed_ids"
            ].append(
                post_id
            )

            channel_state[
                "last_id"
            ] = max(
                int(
                    channel_state[
                        "last_id"
                    ]
                ),
                post_id
            )

            if len(
                channel_state[
                    "processed_ids"
                ]
            ) > MAX_PROCESSED_IDS:

                channel_state[
                    "processed_ids"
                ] = channel_state[
                    "processed_ids"
                ][
                    -MAX_PROCESSED_IDS:
                ]

            # -------------------------------------------------
            # ذخیره فوری
            # -------------------------------------------------

            save_json(
                STATE_FILE,
                state
            )

            continue

        # =================================================
        # NOT DUPLICATE -> SEND
        # =================================================

        result = send_post(
            post,
            username
        )

        if result.get(
            "success"
        ):

            result_type = result.get(
                "type"
            )

            print(
                f"[SUCCESS] @{username} "
                f"post={post_id} "
                f"type={result_type}"
            )

            # -------------------------------------------------
            # CHANNEL STATE
            # -------------------------------------------------

            channel_state[
                "processed_ids"
            ].append(
                post_id
            )

            channel_state[
                "last_id"
            ] = max(
                int(
                    channel_state[
                        "last_id"
                    ]
                ),
                post_id
            )

            if len(
                channel_state[
                    "processed_ids"
                ]
            ) > MAX_PROCESSED_IDS:

                channel_state[
                    "processed_ids"
                ] = channel_state[
                    "processed_ids"
                ][
                    -MAX_PROCESSED_IDS:
                ]

            # -------------------------------------------------
            # GLOBAL HISTORY
            # -------------------------------------------------

            if result_type != "filtered":

                add_global_history(
                    global_state,
                    post,
                    username,
                    result.get(
                        "result"
                    ),
                    result.get(
                        "message_kind"
                    )
                )

            # -------------------------------------------------
            # SAVE IMMEDIATELY
            # -------------------------------------------------

            save_json(
                STATE_FILE,
                state
            )

            time.sleep(
                SEND_DELAY
            )

        else:

            print(
                f"[FAILED] @{username} "
                f"post={post_id}"
            )

            print(
                "[STATE] این پست ثبت نشد؛ "
                "اجرای بعدی دوباره تلاش می‌کند."
            )

            # -------------------------------------------------
            # مهم:
            # در صورت خطا، پردازش کانال را متوقف می‌کنیم
            # تا ترتیب حفظ شود.
            # -------------------------------------------------

            break

    return state


# =========================================================
# MAIN
# =========================================================

def main():

    global CURRENT_CHAT_ID

    print("")
    print(
        "=" * 60
    )
    print(
        "TELEGRAM PUBLIC CHANNEL "
        "FORWARDER"
    )
    print(
        "=" * 60
    )

    # -----------------------------------------------------
    # LOAD
    # -----------------------------------------------------

    channels = load_json(
        CHANNELS_FILE,
        []
    )

    raw_state = load_json(
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

    state = normalize_state(
        raw_state
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
    # TEST
    # -----------------------------------------------------

    if not test_destination():

        print(
            "[STOP] مقصد معتبر نیست."
        )

        return

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
    # CHECK
    # -----------------------------------------------------

    state = check_channels(
        channels,
        state
    )

    # -----------------------------------------------------
    # SAVE
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

    print("")
    print(
        "=" * 60
    )

    print(
        f"[FINAL CHAT ID] "
        f"{CURRENT_CHAT_ID}"
    )

    print(
        f"[GLOBAL HISTORY] "
        f"{len(state['global']['history'])}"
    )

    print(
        "[DONE] اجرای برنامه تمام شد."
    )

    print(
        "=" * 60
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
