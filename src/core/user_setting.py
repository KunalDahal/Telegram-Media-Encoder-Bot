import json
import os
import shutil
import uuid
from typing import Any, Dict

VALID_RESOLUTIONS = ["HDRip", "1080p", "720p", "480p"]
RESOLUTION_ALIASES = {
    "hdrip": "HDRip",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
    "480": "480p",
}

DEFAULT_PROFILES = {
    "HDRip": {"mode": "metadata_only", "crf": None, "preset": None, "codec": None, "audio_bitrate": None},
    "1080p": {"mode": "encode", "crf": 23, "preset": "medium", "codec": "libx264", "audio_bitrate": "192k"},
    "720p":  {"mode": "encode", "crf": 26, "preset": "medium", "codec": "libx264", "audio_bitrate": "128k"},
    "480p":  {"mode": "encode", "crf": 28, "preset": "fast",   "codec": "libx264", "audio_bitrate": "96k"},
}


class UserSettings:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.db_folder = "./src/bin/users"
        self.thumbnails_folder = "./src/bin/thumbnails"
        os.makedirs(self.db_folder, exist_ok=True)
        os.makedirs(self.thumbnails_folder, exist_ok=True)

        self.storage_path = os.path.join(self.db_folder, f"{self.user_id}.json")

        self.data: Dict[str, Any] = {}
        self.temp_state: Dict[int, Dict] = {}

        self._load()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = self._get_default_settings()
        else:
            self.data = self._get_default_settings()

        if "metadata" not in self.data:
            self.data["metadata"] = {"title": "", "author": "", "encoder": ""}
        if "send_type" not in self.data:
            self.data["send_type"] = "media"

        if "profiles" not in self.data:
            self.data["profiles"] = {
                res: profile.copy() for res, profile in DEFAULT_PROFILES.items()
            }
        else:
            # Back-fill any missing resolutions
            for res, profile in DEFAULT_PROFILES.items():
                if res not in self.data["profiles"]:
                    self.data["profiles"][res] = profile.copy()

        self.data["resolutions"] = self._normalize_resolutions(
            self.data.get("resolutions", self.data.get("resolution"))
        )
        self._sync_resolution_alias()

    def _sync_resolution_alias(self):
        resolutions = self.data.get("resolutions") or ["1080p"]
        self.data["resolution"] = resolutions[0]

    def _save(self):
        try:
            self._sync_resolution_alias()
            with open(self.storage_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def _get_default_settings(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "resolutions": ["1080p"],
            "resolution": "1080p",
            "crf": 28,
            "preset": "medium",
            "codec": "libx264",
            "audio_bitrate": "128k",
            "send_type": "media",
            "metadata": {"title": "", "author": "", "encoder": ""},
            "thumbnail_path": "",
            "profiles": {res: profile.copy() for res, profile in DEFAULT_PROFILES.items()},
        }

    def _normalize_resolutions(self, values) -> list:
        if isinstance(values, str):
            values = [values]
        elif not isinstance(values, list):
            values = []

        normalized = []
        for value in values:
            if not isinstance(value, str):
                continue
            clean_value = RESOLUTION_ALIASES.get(value.strip().lower())
            if clean_value and clean_value not in normalized:
                normalized.append(clean_value)

        if not normalized:
            normalized = ["1080p"]

        return normalized[:4]

    # ── Public getters ────────────────────────────────────────────────────────

    def get(self) -> Dict[str, Any]:
        return self.data

    def get_profile(self, resolution: str) -> Dict[str, Any]:
        """Return the stored profile for a resolution, initialising defaults if missing."""
        if "profiles" not in self.data:
            self.data["profiles"] = {
                res: profile.copy() for res, profile in DEFAULT_PROFILES.items()
            }

        if resolution not in self.data["profiles"]:
            self.data["profiles"][resolution] = DEFAULT_PROFILES.get(
                resolution,
                {"mode": "encode", "crf": 23, "preset": "medium",
                 "codec": "libx264", "audio_bitrate": "128k"},
            ).copy()
            self._save()

        return self.data["profiles"][resolution]

    def get_all_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Return all resolution profiles."""
        if "profiles" not in self.data:
            self.data["profiles"] = {
                res: profile.copy() for res, profile in DEFAULT_PROFILES.items()
            }
            self._save()
        return self.data["profiles"]

    def get_effective_settings(
        self, resolution: str, base_overrides: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Return a complete settings dict for a given resolution by merging its
        profile with any caller-supplied overrides (metadata, thumbnail, send_type…).

        HDRip always forces metadata_only mode regardless of profile.
        """
        profile = self.get_profile(resolution)

        # HDRip: no re-encode, copy-only
        if resolution == "HDRip":
            effective = {
                "resolution": resolution,
                "processing_mode": "metadata_only",
                "crf": None,
                "preset": None,
                "codec": None,
                "audio_bitrate": None,
            }
        else:
            effective = {
                "resolution": resolution,
                "processing_mode": profile.get("mode", "encode"),
                "crf": profile.get("crf", 23),
                "preset": profile.get("preset", "medium"),
                "codec": profile.get("codec", "libx264"),
                "audio_bitrate": profile.get("audio_bitrate", "128k"),
            }

        # Layer on any caller overrides (metadata, thumbnail_path, send_type, etc.)
        if base_overrides:
            for key, value in base_overrides.items():
                effective[key] = value

        return effective

    # ── Public mutators ───────────────────────────────────────────────────────

    def update(self, key: str, value: Any):
        if key == "resolution":
            self.set_resolutions([value])
            return
        if key in self.data:
            self.data[key] = value
            self._save()

    def set_resolutions(self, resolutions):
        self.data["resolutions"] = self._normalize_resolutions(resolutions)
        self._save()

    def toggle_resolution(self, resolution: str):
        normalized = self._normalize_resolutions([resolution])[0]
        selected = list(self.data.get("resolutions", ["1080p"]))

        if normalized in selected:
            if len(selected) == 1:
                return False, "At least one resolution must stay selected."
            selected.remove(normalized)
            self.data["resolutions"] = selected
            self._save()
            return True, f"{normalized} removed"

        if len(selected) >= 4:
            return False, "You can select up to 4 resolutions per file."

        selected.append(normalized)
        self.data["resolutions"] = self._normalize_resolutions(selected)
        self._save()
        return True, f"{normalized} added"

    def update_metadata(self, title: str = None, author: str = None, encoder: str = None):
        if "metadata" not in self.data:
            self.data["metadata"] = {}
        if title is not None:
            self.data["metadata"]["title"] = title
        if author is not None:
            self.data["metadata"]["author"] = author
        if encoder is not None:
            self.data["metadata"]["encoder"] = encoder
        self._save()

    def update_profile(self, resolution: str, key: str, value: Any):
        """Update a single field in a resolution profile."""
        if "profiles" not in self.data:
            self.data["profiles"] = {
                res: profile.copy() for res, profile in DEFAULT_PROFILES.items()
            }
        if resolution not in self.data["profiles"]:
            self.data["profiles"][resolution] = DEFAULT_PROFILES.get(
                resolution,
                {"mode": "encode", "crf": 23, "preset": "medium",
                 "codec": "libx264", "audio_bitrate": "128k"},
            ).copy()
        self.data["profiles"][resolution][key] = value
        self._save()

    def reset_profile(self, resolution: str) -> bool:
        """Reset a single profile to factory defaults."""
        if resolution in DEFAULT_PROFILES:
            self.data["profiles"][resolution] = DEFAULT_PROFILES[resolution].copy()
            self._save()
            return True
        return False

    def set_thumbnail(self, path: str):
        if path and os.path.exists(path):
            ext = os.path.splitext(path)[1]
            thumb_filename = f"thumb_{self.user_id}_{uuid.uuid4().hex[:8]}{ext}"
            persistent_path = os.path.join(self.thumbnails_folder, thumb_filename)

            shutil.copy2(path, persistent_path)

            old_thumb = self.data.get("thumbnail_path")
            if (
                old_thumb
                and old_thumb != persistent_path
                and os.path.exists(old_thumb)
                and old_thumb.startswith(self.thumbnails_folder)
            ):
                try:
                    os.remove(old_thumb)
                except Exception:
                    pass

            self.data["thumbnail_path"] = persistent_path
            self._save()

    def reset(self):
        self.data = self._get_default_settings()
        self._save()