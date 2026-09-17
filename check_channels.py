======================== check_channels.py ========================

import os import json import time import re import hashlib from difflib
import SequenceMatcher from datetime import datetime, timezone

import requests from bs4 import BeautifulSoup

BOT_TOKEN = os.environ[“BOT_TOKEN”].strip() ENV_CHAT_ID =
os.environ[“CHAT_ID”].strip() OWNER_ID = int(os.environ[“OWNER_ID”])

CHANNELS_FILE = “channels.json” STATE_FILE = “state.json” BOT_STATE_FILE
= “bot_state.json” API = f”https://api.telegram.org/bot{BOT_TOKEN}”

SEND_DELAY = 2 MAX_PROCESSED_IDS = 1000 MAX_GLOBAL_HISTORY = 1000
SIMILARITY_THRESHOLD = 0.88 MIN_SIMILARITY_LENGTH = 60

HEADERS = { “User-Agent”: ( “Mozilla/5.0 (Windows NT 10.0; Win64; x64)”
“AppleWebKit/537.36 (KHTML, like Gecko)” “Chrome/120.0 Safari/537.36” )
}

FILTER_PATTERNS = [ r”شرط[00c00d_ـ-]بندی”,
r”وین[00c00d_ـ-]تو[00c00d_ـ-]بت”, r”وان[00c00d_ـ-]ایکس”,
r”1[00c00d_ـ-._]x[00c00d_ـ-._]bet”,]

CURRENT_CHAT_ID = ENV_CHAT_ID

class TelegramAPIError(Exception): def init(self, code, description,
parameters=None): self.code = code self.description = description
self.parameters = parameters or {} super().__init__(f”Telegram API error
{code}: {description}“)

def load_json(path, default): if not os.path.exists(path): return
default try: with open(path, “r”, encoding=“utf-8”) as f: return
json.load(f) except Exception as e: print(f”[ERROR] خواندن {path}: {e}“)
return default

def save_json(path, data): tmp = path + “.tmp” with open(tmp, “w”,
encoding=“utf-8”) as f: json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, path)

def normalize_text(text): text = str(text or ““) text =
text.replace(”ي”, “ی”).replace(“ى”, “ی”).replace(“ك”, “ک”) text =
text.replace(“00c”, ” “).replace(”00d”, ” “) text =
text.replace(”“,”“).replace(”060”, ““) return re.sub(r”+“,” “,
text).strip().lower()

def similarity_text(text): text = normalize_text(text) text =
re.sub(r”https?://+|www.+“,” “, text) text = re.sub(r”@+“,” “, text)
text = text.replace(”#“,” “) text = re.sub(r”[^\w\s\u0600-\u06FF]“,” “,
text, flags=re.UNICODE) return re.sub(r”+“,” “, text).strip()

def is_filtered(text): text = normalize_text(text) for pattern in
FILTER_PATTERNS: if re.search(pattern, text, re.IGNORECASE): return
True, pattern return False, None

def telegram_call(method, destination=False, retry_migration=True,
**params): if destination: params[“chat_id”] = CURRENT_CHAT_ID

    try:
        response = requests.post(
            f"{API}/{method}",
            data=params,
            timeout=60
        )
        result = response.json()
    except requests.RequestException as e:
        raise TelegramAPIError(0, f"Network error: {e}")
    except Exception:
        raise TelegramAPIError(
            response.status_code,
            response.text[:500]
        )

    if result.get("ok"):
        return result

    parameters = result.get("parameters", {})
    migrate_to = parameters.get("migrate_to_chat_id")

    if destination and migrate_to and retry_migration:
        update_chat_id(migrate_to)

        retry_params = {
            k: v for k, v in params.items() if k != "chat_id"
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

def update_chat_id(new_id): global CURRENT_CHAT_ID new_id =
str(new_id).strip()

    if new_id and new_id != CURRENT_CHAT_ID:
        print("=" * 60)
        print("[MIGRATION DETECTED]")
        print(f"[OLD CHAT ID] {CURRENT_CHAT_ID}")
        print(f"[NEW CHAT ID] {new_id}")
        print("=" * 60)

    CURRENT_CHAT_ID = new_id

def multipart_call(method, data, files, retry_migration=True): data =
dict(data) data[“chat_id”] = CURRENT_CHAT_ID

    try:
        response = requests.post(
            f"{API}/{method}",
            data=data,
            files=files,
            timeout=180
        )
        result = response.json()
    except requests.RequestException as e:
        raise TelegramAPIError(0, f"Network error: {e}")
    except Exception:
        raise TelegramAPIError(
            response.status_code,
            response.text[:500]
        )

    if result.get("ok"):
        return result

    parameters = result.get("parameters", {})
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

def test_destination(): print(f”[INFO] CHAT_ID = {CURRENT_CHAT_ID}“)
try: result = telegram_call(”getChat”, destination=True) chat =
result.get(“result”, {}) if chat.get(“id”): update_chat_id(chat[“id”])
print(“[OK] مقصد پیدا شد.”) print(f”[CHAT ID] {chat.get(‘id’)}“)
print(f”[CHAT TYPE] {chat.get(‘type’)}“) print(f”[CHAT TITLE]
{chat.get(‘title’)}“) return True except Exception as e: print(f”[FATAL]
مقصد Telegram مشکل دارد: {e}“) return False

def send_message(text): return telegram_call( “sendMessage”,
destination=True, text=text[:4096] )

def send_photo(url, caption=““): return telegram_call(”sendPhoto”,
destination=True, photo=url, caption=caption[:1024] )

def send_video(url, caption=““): return telegram_call(”sendVideo”,
destination=True, video=url, caption=caption[:1024],
supports_streaming=True )

def send_message_to_chat(chat_id, text): return telegram_call(
“sendMessage”, chat_id=chat_id, text=text[:4096] )

def download_file(url): r = requests.get( url, headers=HEADERS,
timeout=180 ) r.raise_for_status()

    filename = url.split("?")[0].rstrip("/").split("/")[-1]
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename) or "media"
    path = f"/tmp/tg_{int(time.time() * 1000)}_{filename}"

    with open(path, "wb") as f:
        f.write(r.content)

    print(f"[DOWNLOAD OK] {path}")
    return path

def send_document(path, caption=““): with open(path,”rb”) as f: return
multipart_call( “sendDocument”, {“caption”: caption[:1024]},
{“document”: f} )

def fetch_posts(username): username = username.strip().lstrip(“@”) r =
requests.get( f”https://t.me/s/{username}“, headers=HEADERS, timeout=60
) r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    posts = []

    for wrap in soup.select("div.tgme_widget_message"):
        data_post = wrap.get("data-post")
        if not data_post:
            continue

        try:
            channel_name, post_id_text = data_post.rsplit("/", 1)
            post_id = int(post_id_text)
        except Exception:
            continue

        text_div = wrap.select_one(".tgme_widget_message_text")
        text = text_div.get_text("\n", strip=True) if text_div else ""

        time_tag = wrap.select_one(".tgme_widget_message_date time")
        published_at = time_tag.get("datetime", "") if time_tag else ""

        photos = []
        for photo in wrap.select("a.tgme_widget_message_photo_wrap"):
            style = photo.get("style", "")
            match = re.search(r"url\(['\"]?([^'\")]+)", style)
            if match:
                photos.append(match.group(1))

        video = None
        video_tag = wrap.select_one("video")
        if video_tag:
            source = video_tag.select_one("source")
            video = source.get("src") if source else video_tag.get("src")

        posts.append({
            "id": post_id,
            "text": text,
            "link": f"https://t.me/{channel_name}/{post_id}",
            "photos": photos,
            "video": video,
            "published_at": published_at
        })

    posts.sort(key=lambda x: x["id"])
    return posts

def media_fingerprint(post): media = []

    for url in post.get("photos", []):
        media.append("photo:" + str(url))

    if post.get("video"):
        media.append("video:" + str(post["video"]))

    if not media:
        return ""

    return hashlib.sha256(
        "|".join(sorted(media)).encode("utf-8", errors="ignore")
    ).hexdigest()

def content_fingerprint(post): raw = similarity_text(post.get(“text”,
““)) raw +=”||” + media_fingerprint(post)

    if not raw.strip():
        raw = str(post.get("id", ""))

    return hashlib.sha256(
        raw.encode("utf-8", errors="ignore")
    ).hexdigest()

def text_similarity(a, b): a = similarity_text(a) b = similarity_text(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if len(a) < MIN_SIMILARITY_LENGTH or len(b) < MIN_SIMILARITY_LENGTH:
        return 0.0

    sequence = SequenceMatcher(None, a, b).ratio()

    wa = set(a.split())
    wb = set(b.split())
    token = len(wa & wb) / len(wa | wb) if wa and wb else 0.0

    return max(sequence, token)

def find_duplicate(post, history): fp = content_fingerprint(post)
media_fp = media_fingerprint(post)

    for item in reversed(history):
        if item.get("fingerprint") == fp:
            return item, "exact content"

        if media_fp and item.get("media_fingerprint") == media_fp:
            old_text = item.get("text", "")
            if not old_text or not post.get("text"):
                return item, "same media"

            if text_similarity(
                post.get("text", ""),
                old_text
            ) >= 0.70:
                return item, "same media + similar text"

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

def build_caption(username, text, link, sources=None): result = ( f”📢
@username” f”{text}” f”🔗 {link}” )

    sources = sources or []

    if len(sources) > 1:
        result += (
            "\n\n📚 منابع مشابه:\n"
            + "\n".join(
                f"• @{s}" for s in dict.fromkeys(sources)
            )
        )

    return result

def add_source_to_original(item, username): sources =
item.setdefault(“sources”, [])

    if username in sources:
        return

    sources.append(username)

    message_id = item.get("message_id")
    if not message_id:
        return

    caption = build_caption(
        item.get("original_username", ""),
        item.get("original_text", ""),
        item.get("original_link", ""),
        sources
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

        print(f"[SOURCE UPDATED] +@{username}")

    except Exception as e:
        print(f"[WARN] بروزرسانی منابع ناموفق بود: {e}")

def send_post(post, username): text = (post.get(“text”) or ““).strip()
link = post[“link”] caption = build_caption(username, text, link)

    filtered, pattern = is_filtered(text)

    if filtered:
        print(
            f"[FILTERED] @{username} "
            f"post={post['id']} pattern={pattern}"
        )
        return {
            "success": True,
            "type": "filtered",
            "result": None,
            "message_kind": None
        }

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
            print(f"[ERROR] ارسال متن: {e}")
            return {"success": False}

    if photos:
        first_result = None
        sent = 0

        for i, url in enumerate(photos):
            cap = caption if i == 0 else ""

            try:
                result = send_photo(url, cap)
                if i == 0:
                    first_result = result
                sent += 1

            except Exception as e:
                print(f"[WARN] ارسال مستقیم عکس: {e}")

                try:
                    path = download_file(url)
                    try:
                        result = send_document(path, cap)
                        if i == 0:
                            first_result = result
                        sent += 1
                    finally:
                        if os.path.exists(path):
                            os.remove(path)

                except Exception as e2:
                    print(f"[ERROR] ارسال عکس: {e2}")

        return {
            "success": sent > 0,
            "type": "sent",
            "result": first_result,
            "message_kind": "caption"
        }

    if video:
        try:
            result = send_video(video, caption)
            return {
                "success": True,
                "type": "sent",
                "result": result,
                "message_kind": "caption"
            }
        except Exception as e:
            print(f"[WARN] ارسال ویدیو: {e}")

        try:
            path = download_file(video)
            try:
                result = send_document(path, caption)
                return {
                    "success": True,
                    "type": "sent",
                    "result": result,
                    "message_kind": "caption"
                }
            finally:
                if os.path.exists(path):
                    os.remove(path)
        except Exception as e:
            print(f"[WARN] آپلود ویدیو: {e}")

        try:
            result = send_message(
                f"🎬 پست جدید از @{username}\n\n"
                f"{text}\n\n🔗 {link}\n\n"
                "⚠️ ارسال مستقیم ویدیو ناموفق بود."
            )
            return {
                "success": True,
                "type": "link",
                "result": result,
                "message_kind": "text"
            }
        except Exception as e:
            print(f"[ERROR] لینک ویدیو: {e}")
            return {"success": False}

    return {"success": False}

def handle_updates(channels, bot_state): offset =
int(bot_state.get(“last_update_id”, 0)) + 1

    try:
        result = telegram_call(
            "getUpdates",
            offset=offset,
            timeout=0
        )
        updates = result.get("result", [])
    except Exception as e:
        print(f"[WARN] getUpdates: {e}")
        return channels, bot_state

    for update in updates:
        bot_state["last_update_id"] = update["update_id"]

        message = update.get("message")
        if not message:
            continue

        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()

        if not text or user_id != OWNER_ID:
            continue

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""

        if command == "/id":
            send_message_to_chat(
                chat_id,
                f"🆔 Chat ID:\n{chat_id}"
            )

        elif command in ("/start", "/help", "/manage"):
            send_message_to_chat(chat_id, HELP_TEXT)

        elif command == "/add":
            username = argument.lstrip("@").strip().lower()

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
            username = argument.lstrip("@").strip().lower()
            old = len(channels)

            channels = [
                c for c in channels
                if c.lower().lstrip("@") != username
            ]

            send_message_to_chat(
                chat_id,
                f"🗑 @{username} حذف شد."
                if len(channels) < old
                else f"❌ @{username} پیدا نشد."
            )

        elif command == "/list":
            send_message_to_chat(
                chat_id,
                "📋 لیست کانال‌ها:\n\n"
                + (
                    "\n".join(f"• @{c}" for c in channels)
                    if channels
                    else "خالی است."
                )
            )

    return channels, bot_state

def normalize_state(raw): if ( isinstance(raw, dict) and “channels” in
raw ): return { “channels”: { name: { “last_id”: int(
value.get(“last_id”, 0) ), “processed_ids”: [ int(x) for x in value.get(
“processed_ids”, [] ) if str(x).isdigit() ][-MAX_PROCESSED_IDS:] } for
name, value in raw.get( “channels”, {} ).items() }, “global”: {
“history”: raw.get( “global”, {} ).get( “history”, []
)[-MAX_GLOBAL_HISTORY:] } }

    # سازگاری با state.json قدیمی:
    channels = {}

    if isinstance(raw, dict):
        for name, value in raw.items():
            try:
                last_id = int(value)
            except Exception:
                last_id = 0

            channels[name] = {
                "last_id": last_id,
                "processed_ids": []
            }

    return {
        "channels": channels,
        "global": {
            "history": []
        }
    }

def published_timestamp(post): value = post.get(“published_at”, ““)

    if not value:
        return 0

    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.timestamp()

    except Exception:
        return 0

def mark_processed(channel_state, post_id): ids =
channel_state.setdefault( “processed_ids”, [] )

    if post_id not in ids:
        ids.append(post_id)

    channel_state["last_id"] = max(
        int(channel_state.get("last_id", 0)),
        post_id
    )

    channel_state["processed_ids"] = (
        ids[-MAX_PROCESSED_IDS:]
    )

def add_history(history, post, username, result, message_kind): message
= ( result.get(“result”, {}) if isinstance(result, dict) else {} )

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

def check_channels(channels, state): channel_states = state[“channels”]
history = state[“global”][“history”] candidates = []

    # اول همه کانال‌ها خوانده می‌شوند تا ترتیب زمانی حفظ شود.
    for index, username in enumerate(channels):
        username = username.strip().lstrip("@").lower()

        try:
            posts = fetch_posts(username)
        except Exception as e:
            print(f"[ERROR] @{username}: {e}")
            continue

        print(f"[FOUND] @{username}: {len(posts)} posts")

        if username not in channel_states:
            channel_states[username] = {
                "last_id": 0,
                "processed_ids": []
            }

        cs = channel_states[username]

        # اجرای اول: آخرین پست فقط baseline است.
        if int(cs["last_id"]) == 0:
            latest = posts[-1] if posts else None
            if latest:
                mark_processed(cs, latest["id"])
                print(
                    f"[INIT] @{username} "
                    f"baseline={latest['id']}"
                )
            continue

        for post in posts:
            pid = int(post["id"])

            if pid <= int(cs["last_id"]):
                continue

            if pid in cs.get("processed_ids", []):
                continue

            candidates.append({
                "username": username,
                "index": index,
                "post": post
            })

    candidates.sort(
        key=lambda x: (
            published_timestamp(x["post"]),
            x["index"],
            x["post"]["id"]
        )
    )

    print(f"[GLOBAL] new candidates={len(candidates)}")

    for item in candidates:
        username = item["username"]
        post = item["post"]
        pid = post["id"]
        cs = channel_states[username]

        filtered, pattern = is_filtered(
            post.get("text", "")
        )

        if filtered:
            print(
                f"[FILTERED] @{username} "
                f"post={pid} pattern={pattern}"
            )
            mark_processed(cs, pid)
            save_json(STATE_FILE, state)
            continue

        duplicate, reason = find_duplicate(
            post,
            history
        )

        if duplicate:
            print(
                f"[GLOBAL DUPLICATE] @{username} "
                f"post={pid} reason={reason}"
            )

            add_source_to_original(
                duplicate,
                username
            )

            mark_processed(cs, pid)
            save_json(STATE_FILE, state)
            continue

        result = send_post(
            post,
            username
        )

        if not result.get("success"):
            print(
                f"[FAILED] @{username} post={pid}; "
                "state will NOT advance."
            )
            break

        mark_processed(cs, pid)

        if result.get("type") != "filtered":
            add_history(
                history,
                post,
                username,
                result.get("result"),
                result.get("message_kind")
            )

        save_json(STATE_FILE, state)

        time.sleep(SEND_DELAY)

    return state

HELP_TEXT = ( “🤖 ربات ارسال پست” “/add username - افزودن کانال”
“/remove username - حذف کانال” “/list - لیست کانال‌ها” “/id - نمایش شناسه
چت فعلی” “/help - راهنما” )

def main(): global CURRENT_CHAT_ID

    channels = load_json(
        CHANNELS_FILE,
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

    if not isinstance(bot_state, dict):
        bot_state = {"last_update_id": 0}

    CURRENT_CHAT_ID = str(
        bot_state.get(
            "destination_chat_id",
            ENV_CHAT_ID
        )
    ).strip()

    print("=" * 60)
    print("TELEGRAM PUBLIC CHANNEL FORWARDER")
    print("=" * 60)
    print(f"[INFO] channels={len(channels)}")
    print(f"[INFO] destination={CURRENT_CHAT_ID}")

    if not test_destination():
        return

    channels, bot_state = handle_updates(
        channels,
        bot_state
    )

    check_channels(
        channels,
        state
    )

    bot_state["destination_chat_id"] = CURRENT_CHAT_ID

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

    print("=" * 60)
    print(f"[FINAL CHAT ID] {CURRENT_CHAT_ID}")
    print("[DONE] اجرای برنامه تمام شد.")
    print("=" * 60)

if name == “main”: try: main() except KeyboardInterrupt: print(“[STOP]
متوقف شد.”) except Exception as e: import traceback print(“=” * 60)
print(“[FATAL ERROR]”) print(f”[ERROR TYPE] {type(e).__name__}“)
print(f”[ERROR] {e}“) traceback.print_exc() print(”=” * 60) raise

======================== GitHub Actions workflow
========================

name: Check Telegram Channels

on: schedule: - cron: “/10  * * *” workflow_dispatch:

permissions: contents: write

concurrency: group: telegram-channel-checker cancel-in-progress: false

jobs: check-channels: runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Check Python syntax
        run: |
          python --version
          python -m py_compile check_channels.py

      - name: Run channel checker
        shell: bash
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}
          OWNER_ID: ${{ secrets.OWNER_ID }}
        run: |
          set -o pipefail
          echo "=========================================="
          echo "START CHANNEL CHECKER"
          echo "=========================================="
          python -u check_channels.py 2>&1 | tee channel_checker.log

      - name: Save state files
        if: always()
        shell: bash
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add channels.json state.json bot_state.json channel_checker.log 2>/dev/null || true

          if git diff --cached --quiet; then
            echo "No state changes to commit."
          else
            git commit -m "Update bot state"
            git push
          fi
