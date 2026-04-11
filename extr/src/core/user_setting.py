import json
import os
import shutil
import uuid
from typing import Any, Dict

VALID_RESOLUTIONS = ["1080p", "720p", "480p"]
RESOLUTION_ALIASES = {
    "1080p": "1080p",
    "720p":  "720p",
    "480p":  "480p",
    "480":   "480p",
}

DEFAULT_PROFILES = {
    "1080p": {"mode": "encode", "crf": 23, "preset": "medium", "codec": "libx264", "audio_bitrate": "192k"},
    "720p":  {"mode": "encode", "crf": 26, "preset": "medium", "codec": "libx264", "audio_bitrate": "128k"},
    "480p":  {"mode": "encode", "crf": 28, "preset": "fast",   "codec": "libx264", "audio_bitrate": "96k"},
}

DEFAULT_WATERMARK = {
    "enabled":      False,
    "text":         "",
    "color":        "white",
    "font_path":    "",
    "font_name":    "default",
    "font_size":    24,
    "padding":      7,
    "timing_mode":  "range",
    "start":        0,
    "end":          0,
    "duration":     30,
    "repeat_count": 1,
    "position":     "bot_right",
}

VALID_WM_POSITIONS = {
    "top_left", "top_mid", "top_right",
    "mid_left", "mid_right",
    "bot_left", "bot_right",
}

DEFAULT_MI_PARAMS: dict = {
    "audio_offset":    0.0,
    "subtitle_offset": 0.0,
    "audio_async":     1,
    "audio_tempo":     1.0,
    "video_fps":       "source",
    "video_vsync":     "cfr",
    "video_pts":       "PTS-STARTPTS",
    "audio_pts":       "PTS-STARTPTS",
    "audio_pad":       False,
    "video_pad":       False,
    "shortest":        True,
    "fix_sub_duration": True,
    "generate_pts":     True,
    "ignore_dts":       False,
    "copy_timestamps":  False,
    "start_at_zero":    False,
}


def _extract_font_name(font_path: str) -> str:
    try:
        from fontTools.ttLib import TTFont
        tt         = TTFont(font_path, fontNumber=0)
        name_table = tt["name"]
        for name_id in (4, 1):
            record = name_table.getName(name_id, 3, 1, 0x0409)
            if record:
                return record.toUnicode().strip()
        for record in name_table.names:
            if record.nameID == 4:
                try:
                    return record.toUnicode().strip()
                except Exception:
                    pass
    except Exception:
        pass
    return os.path.splitext(os.path.basename(font_path))[0]


class UserSettings:
    _temp_state: Dict[int, Dict] = {}

    def __init__(self, user_id: int, paths=None):
        self.user_id = user_id
        if paths is not None:
            self.db_folder          = paths.users
            self.thumbnails_folder  = paths.thumbnails
            self.fonts_folder       = paths.fonts
        else:
            self.db_folder         = "./src/bin/users"
            self.thumbnails_folder = "./src/bin/thumbnails"
            self.fonts_folder      = "./src/bin/fonts"

        os.makedirs(self.db_folder,         exist_ok=True)
        os.makedirs(self.thumbnails_folder,  exist_ok=True)
        os.makedirs(self.fonts_folder,       exist_ok=True)

        self.storage_path = os.path.join(self.db_folder, f"{self.user_id}.json")
        self.data: Dict[str, Any] = {}
        self._load()

    @property
    def temp_state(self) -> Dict[int, Dict]:
        return UserSettings._temp_state

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
        if "auto_detect_thumb" not in self.data:
            self.data["auto_detect_thumb"] = False
        if "profiles" not in self.data:
            self.data["profiles"] = {res: p.copy() for res, p in DEFAULT_PROFILES.items()}
        else:
            for res, profile in DEFAULT_PROFILES.items():
                if res not in self.data["profiles"]:
                    self.data["profiles"][res] = profile.copy()
        if "watermark" not in self.data:
            self.data["watermark"] = DEFAULT_WATERMARK.copy()
        else:
            for key, val in DEFAULT_WATERMARK.items():
                if key not in self.data["watermark"]:
                    self.data["watermark"][key] = val
        if "format" not in self.data:
            self.data["format"] = "{title} S{season}E{episode} [{quality}] [{audio}].mkv"
        if "default_start_episode" not in self.data:
            self.data["default_start_episode"] = 1
        if "default_season" not in self.data:
            self.data["default_season"] = 1
        if "default_audio" not in self.data:
            self.data["default_audio"] = "SUB"

        if "params" not in self.data:
            self.data["params"] = DEFAULT_MI_PARAMS.copy()
        else:
            for key, val in DEFAULT_MI_PARAMS.items():
                if key not in self.data["params"]:
                    self.data["params"][key] = val

        self.data["resolutions"] = self._normalize_resolutions(
            self.data.get("resolutions", self.data.get("resolution"))
        )
        self._sync_resolution_alias()

    def _sync_resolution_alias(self):
        self.data["resolution"] = (self.data.get("resolutions") or ["1080p"])[0]

    def _save(self):
        try:
            self._sync_resolution_alias()
            with open(self.storage_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def _get_default_settings(self) -> Dict[str, Any]:
        return {
            "user_id":              self.user_id,
            "resolutions":          ["1080p"],
            "resolution":           "1080p",
            "crf":                  28,
            "preset":               "medium",
            "codec":                "libx264",
            "audio_bitrate":        "128k",
            "send_type":            "media",
            "auto_detect_thumb":    False,
            "metadata":             {"title": "", "author": "", "encoder": ""},
            "thumbnail_path":       "",
            "profiles":             {res: p.copy() for res, p in DEFAULT_PROFILES.items()},
            "watermark":            DEFAULT_WATERMARK.copy(),
            "format":               "{title} S{season}E{episode} [{quality}] [{audio}].mkv",
            "default_start_episode": 1,
            "default_season":        1,
            "default_audio":         "SUB",
            "params":                DEFAULT_MI_PARAMS.copy(),
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
            clean = RESOLUTION_ALIASES.get(value.strip().lower())
            if clean and clean not in normalized:
                normalized.append(clean)
        return normalized[:4] if normalized else ["1080p"]

    def get(self) -> Dict[str, Any]:
        return self.data

    def get_profile(self, resolution: str) -> Dict[str, Any]:
        if "profiles" not in self.data:
            self.data["profiles"] = {res: p.copy() for res, p in DEFAULT_PROFILES.items()}
        if resolution not in self.data["profiles"]:
            self.data["profiles"][resolution] = DEFAULT_PROFILES.get(
                resolution,
                {"mode": "encode", "crf": 23, "preset": "medium",
                 "codec": "libx264", "audio_bitrate": "128k"},
            ).copy()
            self._save()
        return self.data["profiles"][resolution]

    def get_all_profiles(self) -> Dict[str, Dict[str, Any]]:
        if "profiles" not in self.data:
            self.data["profiles"] = {res: p.copy() for res, p in DEFAULT_PROFILES.items()}
            self._save()
        return self.data["profiles"]

    def get_watermark(self) -> Dict[str, Any]:
        if "watermark" not in self.data:
            self.data["watermark"] = DEFAULT_WATERMARK.copy()
        for key, val in DEFAULT_WATERMARK.items():
            if key not in self.data["watermark"]:
                self.data["watermark"][key] = val
        return self.data["watermark"]

    def get_effective_settings(self, resolution: str, base_overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        profile = self.get_profile(resolution)
        effective = {
            "resolution":      resolution,
            "processing_mode": profile.get("mode", "encode"),
            "crf":             profile.get("crf", 23),
            "preset":          profile.get("preset", "medium"),
            "codec":           profile.get("codec", "libx264"),
            "audio_bitrate":   profile.get("audio_bitrate", "128k"),
        }
        if base_overrides:
            effective.update(base_overrides)
        return effective

    def update(self, key: str, value: Any):
        if key == "resolution":
            self.set_resolutions([value])
            return
        self.data[key] = value
        self._save()

    def set_resolutions(self, resolutions):
        self.data["resolutions"] = self._normalize_resolutions(resolutions)
        self._save()

    def toggle_resolution(self, resolution: str):
        normalized = self._normalize_resolutions([resolution])[0]
        selected   = list(self.data.get("resolutions", ["1080p"]))
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
        if title   is not None: self.data["metadata"]["title"]   = title
        if author  is not None: self.data["metadata"]["author"]  = author
        if encoder is not None: self.data["metadata"]["encoder"] = encoder
        self._save()

    def update_profile(self, resolution: str, key: str, value: Any):
        if "profiles" not in self.data:
            self.data["profiles"] = {res: p.copy() for res, p in DEFAULT_PROFILES.items()}
        if resolution not in self.data["profiles"]:
            self.data["profiles"][resolution] = DEFAULT_PROFILES.get(
                resolution,
                {"mode": "encode", "crf": 23, "preset": "medium",
                 "codec": "libx264", "audio_bitrate": "128k"},
            ).copy()
        self.data["profiles"][resolution][key] = value
        self._save()

    def reset_profile(self, resolution: str) -> bool:
        if resolution in DEFAULT_PROFILES:
            self.data["profiles"][resolution] = DEFAULT_PROFILES[resolution].copy()
            self._save()
            return True
        return False

    def update_watermark(self, **kwargs):
        wm = self.get_watermark()
        for key, value in kwargs.items():
            if key in DEFAULT_WATERMARK:
                wm[key] = value
        self.data["watermark"] = wm
        self._save()

    def set_watermark_font(self, tmp_path: str) -> str:
        if not tmp_path or not os.path.exists(tmp_path):
            return "default"
        ext = os.path.splitext(tmp_path)[1].lower()
        if ext not in (".ttf", ".otf"):
            return "default"

        font_filename = f"font_{self.user_id}_{uuid.uuid4().hex[:8]}{ext}"
        dest_path     = os.path.abspath(os.path.join(self.fonts_folder, font_filename))
        shutil.copy2(tmp_path, dest_path)

        old_path   = self.data.get("watermark", {}).get("font_path", "")
        fonts_abs  = os.path.abspath(self.fonts_folder)
        if (
            old_path
            and old_path != dest_path
            and os.path.exists(old_path)
            and os.path.abspath(old_path).startswith(fonts_abs)
        ):
            try:
                os.remove(old_path)
            except Exception:
                pass

        font_name = _extract_font_name(dest_path)
        self.update_watermark(font_path=dest_path, font_name=font_name)
        return font_name

    def reset_watermark(self):
        old_font = self.data.get("watermark", {}).get("font_path", "")
        if old_font and os.path.exists(old_font):
            try:
                os.remove(old_font)
            except Exception:
                pass
        self.data["watermark"] = DEFAULT_WATERMARK.copy()
        self._save()

    def set_thumbnail(self, path: str):
        if not path or not os.path.exists(path):
            return
        persistent_path = os.path.abspath(
            os.path.join(self.thumbnails_folder, f"thumb_{self.user_id}.jpg")
        )
        shutil.copy2(path, persistent_path)
        src_abs    = os.path.abspath(path)
        thumbs_abs = os.path.abspath(self.thumbnails_folder)
        if src_abs != persistent_path and not src_abs.startswith(thumbs_abs):
            try:
                os.remove(src_abs)
            except Exception:
                pass

        self.data["thumbnail_path"] = persistent_path
        self._save()

    def clear_thumbnail(self):
        old_thumb = self.data.get("thumbnail_path")
        thumbs_abs = os.path.abspath(self.thumbnails_folder)
        if (
            old_thumb
            and os.path.exists(old_thumb)
            and os.path.abspath(old_thumb).startswith(thumbs_abs)
        ):
            try:
                os.remove(old_thumb)
            except Exception:
                pass
        self.data["thumbnail_path"] = ""
        self._save()

    def get_params(self) -> Dict[str, Any]:
        if "params" not in self.data:
            self.data["params"] = DEFAULT_MI_PARAMS.copy()
        else:
            for key, val in DEFAULT_MI_PARAMS.items():
                if key not in self.data["params"]:
                    self.data["params"][key] = val
        return self.data["params"]

    def update_param(self, key: str, value: Any) -> bool:
        if key not in DEFAULT_MI_PARAMS:
            return False
        params = self.get_params()
        params[key] = value
        self.data["params"] = params
        self._save()
        return True

    def reset_params(self):
        self.data["params"] = DEFAULT_MI_PARAMS.copy()
        self._save()

    def reset(self):
        self.data = self._get_default_settings()
        self._save()

    def get_format(self) -> str:
        return self.data.get("format", "{title} S{season}E{episode} [{quality}] [{audio}].mkv")

    def set_format(self, fmt: str):
        self.data["format"] = fmt
        self._save()