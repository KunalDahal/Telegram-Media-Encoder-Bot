import os
import shutil
import sys
from typing import List
from dotenv import load_dotenv


def _find_binary(name: str, local_dir: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    local_path = os.path.join(local_dir, f"{name}{exe_suffix}")
    if os.path.isfile(local_path):
        return local_path
    return name


class Paths:

    def __init__(self, base_dir: str):
        self.base       = base_dir
        self.bin        = os.path.join(base_dir, "bin")
        self.tmp        = os.path.join(base_dir, "bin", "tmp")
        self.logs       = os.path.join(base_dir, "bin", "logs")
        self.thumbnails = os.path.join(base_dir, "bin", "thumbnails")
        self.users      = os.path.join(base_dir, "bin", "users")
        self.fonts      = os.path.join(base_dir, "bin", "fonts")
        self.templates  = os.path.join(base_dir, "templates")

        bin_dir         = os.path.join(base_dir, "bin")
        self.ffmpeg     = _find_binary("ffmpeg",  bin_dir)
        self.ffprobe    = _find_binary("ffprobe", bin_dir)

        self.start_image   = "https://i.ibb.co/N6Fc2mbZ/start.png"
        self.help_banner   = os.path.join(base_dir, "templates", "help.jpg")
        self.default_thumb = os.path.join(base_dir, "bin", "default.jpg")

    def makedirs(self):
        for d in (self.tmp, self.logs, self.thumbnails, self.users, self.fonts):
            os.makedirs(d, exist_ok=True)


class Config:
    _SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def __init__(self):
        load_dotenv()

        # ── Main bot (DC4) ────────────────────────────────────────────────────
        self.bot_token: str = os.getenv("BOT_TOKEN", "")

        # ── Secondary bot (DC5) — optional ───────────────────────────────────
        # If DC5_BOT_TOKEN is set, the secondary bot will be started and used
        # to download files that live on DC 5.
        self.dc5_bot_token: str = os.getenv("DC5_BOT_TOKEN", "")

        # ── Shared Telegram API credentials ───────────────────────────────────
        self.api_id:    int = int(os.getenv("API_ID", "0"))
        self.api_hash:  str = os.getenv("API_HASH", "")

        self.allowed_group_ids: List[int] = self._parse_int_list(
            os.getenv("ALLOWED_GROUP_IDS", "0")
        )
        self.admin_ids: List[int] = self._parse_int_list(
            os.getenv("ADMIN_IDS", "")
        )

        self.paths = Paths(self._SRC_DIR)

        self._validate()

    @property
    def has_dc5_bot(self) -> bool:
        """True when a secondary DC5 bot token has been configured."""
        return bool(self.dc5_bot_token)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_int_list(raw: str) -> List[int]:
        if not raw:
            return []
        result = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                try:
                    result.append(int(part))
                except ValueError:
                    pass
        return result

    def _validate(self):
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required")
        if not self.api_id:
            raise ValueError("API_ID is required")
        if not self.api_hash:
            raise ValueError("API_HASH is required")
        if not self.allowed_group_ids or self.allowed_group_ids[0] == 0:
            raise ValueError("ALLOWED_GROUP_IDS is required")