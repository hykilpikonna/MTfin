import argparse
import concurrent.futures
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import html
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse

import requests


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.toml"
IMDB_ID_RE = re.compile(r"\btt\d{7,}\b", re.IGNORECASE)
PROGRESS_RE = re.compile(r"Progress:\s*(?P<progress>[0-9.]+%)\s*\(State:\s*(?P<state>[^)]+)\)")
TELEGRAM_TEXT_LIMIT = 4096


class TelegramApiError(RuntimeError):
    pass


class TelegramBotClient:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._local = threading.local()

    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def request(self, method: str, **params) -> dict:
        response = self.session().post(f"{self.base_url}/{method}", json=params, timeout=45)
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if not payload.get("ok"):
            description = payload.get("description", "unknown Telegram API error")
            raise TelegramApiError(description)
        response.raise_for_status()
        return payload["result"]

    def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict]:
        params = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = offset

        response = self.session().post(f"{self.base_url}/getUpdates", json=params, timeout=timeout + 10)
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if not payload.get("ok"):
            description = payload.get("description", "unknown Telegram API error")
            raise TelegramApiError(description)
        response.raise_for_status()
        return payload["result"]

    def send_message(self, chat_id: int, text: str) -> dict:
        return self.request(
            "sendMessage",
            chat_id=chat_id,
            text=truncate_telegram_text(text),
            disable_web_page_preview=True,
        )

    def edit_message(self, chat_id: int, message_id: int, text: str) -> dict:
        return self.request(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=truncate_telegram_text(text),
            disable_web_page_preview=True,
        )


@dataclass(frozen=True)
class BotConfig:
    token: str
    dl_dir: str
    jellyfin_dir: str
    imdb_source: str
    ignore_existing: bool
    allowed_chat_ids: frozenset[int]
    workers: int
    progress_interval: float


def load_config(config_file: Path = CONFIG_FILE) -> BotConfig:
    config = tomllib.loads(config_file.read_text(encoding="utf-8"))
    telegram_config = config.get("telegram", {})

    token = telegram_config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Missing Telegram bot token. Set [telegram].bot_token or TELEGRAM_BOT_TOKEN.")

    paths = config["paths"]
    allowed_chat_ids = frozenset(int(chat_id) for chat_id in telegram_config.get("allowed_chat_ids", []))
    imdb_source = str(telegram_config.get("imdb_source", "imdbapi"))
    if imdb_source not in {"imdbapi", "mteam"}:
        raise ValueError("[telegram].imdb_source must be either 'imdbapi' or 'mteam'.")

    return BotConfig(
        token=token,
        dl_dir=str(telegram_config.get("dl_dir") or paths["qb_download_dir"]),
        jellyfin_dir=str(telegram_config.get("jellyfin_dir") or paths["jellyfin_dir"]),
        imdb_source=imdb_source,
        ignore_existing=bool(telegram_config.get("ignore_existing", False)),
        allowed_chat_ids=allowed_chat_ids,
        workers=max(1, int(telegram_config.get("workers", 2))),
        progress_interval=max(2.0, float(telegram_config.get("progress_interval", 10.0))),
    )


def extract_imdb_id(text: str) -> str | None:
    current = text.strip()
    seen = set()

    for _ in range(6):
        match = IMDB_ID_RE.search(current)
        if match:
            return match.group(0).lower()

        seen.add(current)
        decoded = urllib.parse.unquote_plus(html.unescape(current))
        if decoded == current or decoded in seen:
            break
        current = decoded

    return None


def truncate_telegram_text(text: str) -> str:
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return text
    return text[: TELEGRAM_TEXT_LIMIT - 120] + "\n...\n[truncated]"


def tail_text(lines: deque[str], max_chars: int = 2200) -> str:
    selected = []
    total = 0

    for line in reversed(lines):
        line_len = len(line) + 1
        if selected and total + line_len > max_chars:
            break
        selected.append(line)
        total += line_len

    return "\n".join(reversed(selected))


class ProgressReporter:
    def __init__(self, bot: TelegramBotClient, chat_id: int, message_id: int, imdb_id: str, interval: float):
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.imdb_id = imdb_id
        self.interval = interval
        self.started_at = datetime.now()
        self.last_edit_at = 0.0
        self.last_text = ""
        self.title = ""
        self.step = "Starting"
        self.progress = ""
        self.state = ""
        self.lines: deque[str] = deque(maxlen=14)

    def observe(self, line: str) -> None:
        clean_line = line.strip()
        if not clean_line:
            return

        self.lines.append(clean_line)

        if clean_line.startswith("==="):
            self.step = clean_line.strip("= ")
        elif clean_line.startswith("Found Title:"):
            self.title = clean_line.removeprefix("Found Title:").strip()
        elif progress_match := PROGRESS_RE.search(clean_line):
            self.progress = progress_match.group("progress")
            self.state = progress_match.group("state")
        elif clean_line == "Download complete!":
            self.progress = "100.0%"
            self.state = "complete"
        elif clean_line.startswith("Finished processing"):
            self.step = clean_line

    def status_text(self, status: str, log_path: Path | None = None, return_code: int | None = None) -> str:
        elapsed = int((datetime.now() - self.started_at).total_seconds())
        parts = [
            f"{status}: {self.imdb_id}",
            f"Step: {self.step}",
        ]

        if self.title:
            parts.append(f"Title: {self.title}")
        if self.progress:
            parts.append(f"Progress: {self.progress}" + (f" ({self.state})" if self.state else ""))
        if return_code is not None:
            parts.append(f"Exit code: {return_code}")
        parts.append(f"Elapsed: {elapsed}s")
        if log_path is not None:
            parts.append(f"Log: {log_path}")

        recent = tail_text(self.lines)
        if recent:
            parts.append(f"\nRecent output:\n{recent}")

        return "\n".join(parts)

    def flush(self, status: str = "Running", log_path: Path | None = None, return_code: int | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_edit_at < self.interval:
            return

        text = self.status_text(status=status, log_path=log_path, return_code=return_code)
        if text == self.last_text:
            return

        try:
            self.bot.edit_message(self.chat_id, self.message_id, text)
            self.last_edit_at = now
            self.last_text = text
        except TelegramApiError as exc:
            if "message is not modified" in str(exc).lower():
                self.last_edit_at = now
                self.last_text = text
                return
            try:
                message = self.bot.send_message(self.chat_id, text)
                self.message_id = int(message["message_id"])
                self.last_edit_at = now
                self.last_text = text
            except Exception as send_exc:
                print(f"Telegram progress fallback failed: {send_exc}")
        except Exception as exc:
            print(f"Telegram progress update failed: {exc}")


def workflow_command(imdb_id: str, config: BotConfig) -> list[str]:
    cmd = [
        sys.executable,
        "-u",
        str(BASE_DIR / "workflow.py"),
        imdb_id,
        "--dl-dir",
        config.dl_dir,
        "--jellyfin-dir",
        config.jellyfin_dir,
        "--imdb-source",
        config.imdb_source,
    ]
    if config.ignore_existing:
        cmd.append("--ignore-existing")
    return cmd


def run_download_job(bot: TelegramBotClient, chat_id: int, message_id: int, imdb_id: str, config: BotConfig, active_jobs: set[str], active_lock: threading.Lock) -> None:
    logs_dir = BASE_DIR / "logs"
    errors_dir = BASE_DIR / "errors"
    logs_dir.mkdir(exist_ok=True)
    errors_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"telegram_{imdb_id}_{timestamp}.log"
    reporter = ProgressReporter(bot, chat_id, message_id, imdb_id, config.progress_interval)
    reporter.flush(status="Starting", log_path=log_path, force=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    return_code = 1
    final_log_path = log_path

    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                workflow_command(imdb_id, config),
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            assert process.stdout is not None
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
                reporter.observe(line)
                reporter.flush(status="Running", log_path=log_path)

            return_code = process.wait()

        if return_code != 0:
            final_log_path = errors_dir / log_path.name
            log_path.rename(final_log_path)
            reporter.flush(status="Failed", log_path=final_log_path, return_code=return_code, force=True)
        else:
            reporter.flush(status="Completed", log_path=final_log_path, return_code=return_code, force=True)
    except Exception as exc:
        reporter.lines.append(f"Bot adapter error: {exc}")
        reporter.flush(status="Failed", log_path=final_log_path, return_code=return_code, force=True)
    finally:
        with active_lock:
            active_jobs.discard(imdb_id)


def is_chat_allowed(chat_id: int, config: BotConfig) -> bool:
    return not config.allowed_chat_ids or chat_id in config.allowed_chat_ids


def help_text() -> str:
    return (
        "Send /download tt0903747, or /download with any URL/text that contains one after URL decoding.\n"
        "If group privacy mode is disabled, plain tt0903747 messages also work.\n"
        "The bot will start the existing MTfin workflow and keep this chat updated with progress."
    )


def handle_message(
    bot: TelegramBotClient,
    message: dict,
    config: BotConfig,
    executor: concurrent.futures.ThreadPoolExecutor,
    active_jobs: set[str],
    active_lock: threading.Lock,
) -> None:
    chat = message.get("chat") or {}
    chat_id = int(chat.get("id"))
    text = (message.get("text") or message.get("caption") or "").strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""

    if command == "/chatid":
        bot.send_message(chat_id, f"Chat ID: {chat_id}")
        return

    if not is_chat_allowed(chat_id, config):
        bot.send_message(chat_id, "This chat is not allowed to start downloads.")
        return

    if command in {"/start", "/help"}:
        bot.send_message(chat_id, help_text())
        return

    if command == "/status":
        with active_lock:
            running = sorted(active_jobs)
        bot.send_message(chat_id, "Active jobs: " + (", ".join(running) if running else "none"))
        return

    if command and command not in {"/download", "/add"}:
        bot.send_message(chat_id, help_text())
        return

    imdb_id = extract_imdb_id(text)
    if imdb_id is None:
        bot.send_message(chat_id, "I could not find an IMDb title ID. Send something like tt0903747 or an IMDb URL.")
        return

    with active_lock:
        if imdb_id in active_jobs:
            bot.send_message(chat_id, f"{imdb_id} is already queued or running.")
            return
        active_jobs.add(imdb_id)

    try:
        status_message = bot.send_message(chat_id, f"Queued: {imdb_id}")
        executor.submit(
            run_download_job,
            bot,
            chat_id,
            int(status_message["message_id"]),
            imdb_id,
            config,
            active_jobs,
            active_lock,
        )
    except Exception:
        with active_lock:
            active_jobs.discard(imdb_id)
        raise


def run_bot(config: BotConfig) -> None:
    bot = TelegramBotClient(config.token)
    active_jobs: set[str] = set()
    active_lock = threading.Lock()
    next_offset = None

    print(f"Telegram bot is polling. Workers: {config.workers}")
    if not config.allowed_chat_ids:
        print("Warning: no [telegram].allowed_chat_ids configured; any chat can start downloads.")

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.workers) as executor:
        while True:
            try:
                updates = bot.get_updates(next_offset)
            except Exception as exc:
                print(f"Polling error: {exc}")
                time.sleep(5)
                continue

            for update in updates:
                next_offset = int(update["update_id"]) + 1
                message = update.get("message")
                if not message:
                    continue

                try:
                    handle_message(bot, message, config, executor, active_jobs, active_lock)
                except Exception as exc:
                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    print(f"Message handling error: {exc}")
                    if chat_id is not None:
                        try:
                            bot.send_message(int(chat_id), f"Bot adapter error: {exc}")
                        except Exception as send_exc:
                            print(f"Failed to report message handling error: {send_exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram bot adapter for starting MTfin downloads.")
    parser.parse_args()

    config = load_config()
    run_bot(config)


if __name__ == "__main__":
    main()
