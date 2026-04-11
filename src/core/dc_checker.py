"""
dc_checker.py
─────────────
Utility to detect which Telegram Data-Centre (DC) a file lives on,
and to pick the right bot client for downloading it.

How DC detection works
───────────────────────
We use Pyrogram's own FileId.decode() — it handles the internal RLE
encoding and binary format so the DC id is always read correctly.

Reference: https://core.telegram.org/api/files  (DC numbering: 1-5)
"""

import logging
from pyrogram.file_id import FileId

logger = logging.getLogger(__name__)

MAIN_BOT_DC = 4
DC5_BOT_DC  = 5


def get_file_dc(file_id: str) -> int | None:
    """
    Extract the DC id from a Telegram file_id using Pyrogram's own decoder.
    Returns the DC id (1-5) or None on failure.
    """
    try:
        decoded = FileId.decode(file_id)
        dc_id   = decoded.dc_id
        if dc_id and 1 <= dc_id <= 5:
            logger.debug("[DCChecker] file_id %s… → DC%d", file_id[:20], dc_id)
            return dc_id
        logger.warning("[DCChecker] Unexpected DC id %s for file_id %s…", dc_id, file_id[:20])
        return None
    except Exception as exc:
        logger.warning("[DCChecker] Could not decode file_id %s…: %s", file_id[:20], exc)
        return None


def pick_download_client(file_id: str, main_client, dc5_client):
    """
    Return the appropriate Pyrogram client for downloading:
      - DC 5  → dc5_client  (second bot)
      - anything else / unknown → main_client  (main bot, DC 4)
    """
    if dc5_client is None:
        return main_client

    dc = get_file_dc(file_id)

    if dc == DC5_BOT_DC:
        logger.info("[DCChecker] file_id %s… is DC5 → using dc5_bot", file_id[:20])
        return dc5_client

    logger.info("[DCChecker] file_id %s… is DC%s → using main_bot", file_id[:20], dc)
    return main_client