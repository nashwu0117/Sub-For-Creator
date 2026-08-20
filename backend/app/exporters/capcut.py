"""CapCut / JianYing (剪映) draft export.

Produces a ZIP containing a CapCut desktop draft folder that a user can
unzip into their CapCut drafts directory and open in the app::

    <draft_name>/
    ├── draft_content.json     # project JSON (Windows CapCut)
    ├── draft_info.json        # same project JSON (macOS CapCut / JianYing)
    └── draft_meta_info.json   # draft metadata sidecar

Schema research (real OSS examples, checked 2026-08):

- ``GuanYixuan/pyJianYingDraft`` (Apache-2.0) — a Python library that
  generates JianYing drafts. Its ``assets/draft_content_template.json`` and
  ``text_segment.py`` define the text-material ``content`` JSON-in-JSON
  structure (``{"text": ..., "styles": [{"range": [0, n], "fill": {...},
  "size": ..., ...}]}``) and the ``draft_meta_info.json`` sidecar shape.
- ``renezander030/capcut-cli`` (MIT) — edits real CapCut drafts.
  ``docs/draft-schema/00-overview.md`` / ``01-tracks-and-segments.md`` /
  ``02-materials.md`` document the track/segment/material shapes, and
  ``src/caption.ts`` shows the exact minimal text-track + text-material
  structure CapCut accepts for imported captions (the closest analogue to
  this exporter).
- ``notinmood/JianyingDraft.PY`` (MIT) — commits real saved drafts
  (``.draftDemo/Temp/T3/draft_content.json``) confirming the full
  ``draft_meta_info.json`` / ``draft_content.json`` layout.

Key facts encoded here:

- All timestamps are **microseconds** (``target_timerange.start/duration``).
- A text segment references its text material via ``material_id``; the actual
  text lives in ``materials.texts[].content`` as a JSON-encoded string.
- ``content.styles[].range`` is ``[0, len(text)]`` in UTF-16 code units
  (== Python ``len`` for BMP text; astral chars count as 2 units).
- ``draft_info.json`` and ``draft_content.json`` are the same project JSON
  (Windows vs macOS filename); ``draft_meta_info.json`` is the metadata
  sidecar whose ``draft_id`` matches the project ``id``.
- ``clip`` must be an object on text segments (only audio segments use null).

Assumptions / tuning notes (best-effort, conservative):

- Only a text track is emitted (no video/audio materials), so the draft opens
  as a caption-only project; the user drops their media in afterwards.
- ``clip.transform.y = -0.6`` places captions in the lower third (matches
  capcut-cli's caption path and pyJianYingDraft's subtitle convention).
- ``font_size`` uses CapCut's caption scale (default 15.0, as capcut-cli
  does); the ASS exporter's 64pt scale does not apply here.
- Durations are not pre-quantised to the frame grid; CapCut snaps them on
  first open (sub-frame drift is expected and harmless).
- ``platform.app_source`` is ``"lv"`` (JianYing); CapCut International uses
  ``"cc"``. Both open the same draft, but if a CapCut-only install rejects
  the draft, flip this to ``"cc"``.
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile

from ..core.exceptions import ExportError
from ..core.models import TranscriptionResult

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_US_PER_SECOND = 1_000_000
_MIN_DURATION_US = 1  # CapCut rejects zero-length segments

#: Empty material buckets required by the draft_content schema (from the
#: pyJianYingDraft ``draft_content_template.json``).
_EMPTY_MATERIAL_BUCKETS = (
    "ai_translates",
    "audio_balances",
    "audio_effects",
    "audio_fades",
    "audio_track_indexes",
    "audios",
    "beats",
    "canvases",
    "chromas",
    "color_curves",
    "digital_humans",
    "drafts",
    "effects",
    "flowers",
    "green_screens",
    "handwrites",
    "hsl",
    "images",
    "log_color_wheels",
    "loudnesses",
    "manual_deformations",
    "masks",
    "material_animations",
    "material_colors",
    "multi_language_refs",
    "placeholders",
    "plugin_effects",
    "primary_color_wheels",
    "realtime_denoises",
    "shapes",
    "smart_crops",
    "smart_relights",
    "sound_channel_mappings",
    "speeds",
    "stickers",
    "tail_leaders",
    "text_templates",
    "texts",
    "time_marks",
    "transitions",
    "video_effects",
    "video_trackings",
    "videos",
    "vocal_beautifys",
    "vocal_separations",
)


def _to_us(seconds: float) -> int:
    """Convert seconds to microseconds (rounded)."""
    return int(round(seconds * _US_PER_SECOND))


def _duration_us(start: float, end: float) -> int:
    """Segment duration in microseconds, clamped to a 1µs minimum."""
    return max(_MIN_DURATION_US, _to_us(end) - _to_us(start))


def _total_duration_us(result: TranscriptionResult) -> int:
    """Timeline length in microseconds (media_duration, else last segment end)."""
    if result.media_duration is not None:
        return max(0, _to_us(result.media_duration))
    if result.segments:
        return max(0, _to_us(result.segments[-1].end))
    return 0


def _hex_to_rgb_floats(hex_color: str) -> list[float]:
    """Convert ``#RRGGBB`` to a ``[r, g, b]`` list in the 0..1 range."""
    return [int(hex_color[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]


def _safe_draft_name(name: str) -> str:
    """Sanitize a draft folder name for use as a ZIP entry path."""
    cleaned = re.sub(r"[/\\]", "_", name).strip()
    cleaned = re.sub(r"\.\.+", "_", cleaned)
    return cleaned or "capcut_draft"


def _text_material(text: str, font_size: float, color: list[float]) -> dict:
    """Build one ``materials.texts`` entry (the JSON-in-JSON content field)."""
    content = {
        "text": text,
        "styles": [
            {
                "range": [0, len(text)],
                "fill": {
                    "alpha": 1.0,
                    "content": {
                        "render_type": "solid",
                        "solid": {"alpha": 1.0, "color": color},
                    },
                },
                "size": font_size,
                "bold": False,
                "italic": False,
                "underline": False,
                "strokes": [],
            }
        ],
        "layer_weight": 1,
        "effect": [],
    }
    return {
        "id": str(uuid.uuid4()),
        "type": "text",
        "content": json.dumps(content, ensure_ascii=False),
        "font_size": font_size,
        "text_color": "#FFFFFFFF",
        "alignment": 1,  # 0=left, 1=centre, 2=right
        "sub_type": 1,  # caption/subtitle material
        "caption_template_info": {
            "category_id": "",
            "category_name": "",
            "effect_id": "",
            "is_new": False,
            "resource_id": "",
        },
        "typesetting": 0,
        "letter_spacing": 0.0,
        "line_spacing": 0.02,
        "line_feed": 1,
        "line_max_width": 0.82,
        "force_apply_line_max_width": False,
        "check_flag": 7,
        "global_alpha": 1.0,
    }


def _text_segment(material_id: str, start_us: int, duration_us: int) -> dict:
    """Build one text-track segment referencing ``material_id``."""
    return {
        "id": str(uuid.uuid4()),
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "source_timerange": {"start": 0, "duration": duration_us},
        "clip": {
            "alpha": 1.0,
            "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": -0.6},
        },
        "speed": 1.0,
        "volume": 1.0,
        "visible": True,
        "render_index": 0,
        "extra_material_refs": [],
        "common_keyframes": [],
        "uniform_scale": {"on": True, "value": 1.0},
        "group_id": "",
        "track_render_index": 0,
        "enable_adjust": True,
        "enable_color_curves": True,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "cartoon": False,
        "intensifies_audio": False,
        "last_nonzero_volume": 1.0,
        "is_placeholder": False,
        "is_tone_modify": False,
        "reverse": False,
        "track_attribute": 0,
        "template_id": "",
        "template_scene": "default",
        "keyframe_refs": [],
    }


def _draft_content(
    result: TranscriptionResult,
    draft_id: str,
    draft_name: str,
    width: int,
    height: int,
    fps: int,
    font_size: float,
    font_color: str,
) -> dict:
    """Build the ``draft_content.json`` project document."""
    materials = {bucket: [] for bucket in _EMPTY_MATERIAL_BUCKETS}
    segments: list[dict] = []
    text_materials: list[dict] = []
    for seg in result.segments:
        text = seg.text.replace("\r\n", "\n").replace("\n", " ")
        material = _text_material(text, font_size, _hex_to_rgb_floats(font_color))
        text_materials.append(material)
        segments.append(
            _text_segment(material["id"], _to_us(seg.start), _duration_us(seg.start, seg.end))
        )
    materials["texts"] = text_materials

    return {
        "canvas_config": {"height": height, "ratio": "original", "width": width},
        "color_space": 0,
        "config": {
            "adjust_max_index": 1,
            "attachment_info": [],
            "combination_max_index": 1,
            "export_range": None,
            "extract_audio_last_index": 1,
            "lyrics_recognition_id": "",
            "lyrics_sync": True,
            "lyrics_taskinfo": [],
            "maintrack_adsorb": True,
            "material_save_mode": 0,
            "multi_language_current": "none",
            "multi_language_list": [],
            "multi_language_main": "none",
            "multi_language_mode": "none",
            "original_sound_last_index": 1,
            "record_audio_last_index": 1,
            "sticker_max_index": 1,
            "subtitle_keywords_config": None,
            "subtitle_recognition_id": "",
            "subtitle_sync": True,
            "subtitle_taskinfo": [],
            "system_font_list": [],
            "video_mute": False,
            "zoom_info_params": None,
        },
        "cover": None,
        "create_time": 0,
        "duration": _total_duration_us(result),
        "extra_info": None,
        "fps": float(fps),
        "free_render_index_mode_on": False,
        "group_container": None,
        "id": draft_id,
        "keyframe_graph_list": [],
        "keyframes": {
            "adjusts": [],
            "audios": [],
            "effects": [],
            "filters": [],
            "handwrites": [],
            "stickers": [],
            "texts": [],
            "videos": [],
        },
        "last_modified_platform": {
            "app_id": 3704,
            "app_source": "lv",
            "app_version": "5.9.0",
            "os": "windows",
        },
        "materials": materials,
        "mutable_config": None,
        "name": draft_name,
        "new_version": "110.0.0",
        "platform": {
            "app_id": 3704,
            "app_source": "lv",
            "app_version": "5.9.0",
            "os": "windows",
        },
        "relationships": [],
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "source": "default",
        "static_cover_image_path": "",
        "time_marks": None,
        "tracks": [
            {
                "attribute": 0,
                "flag": 0,
                "id": str(uuid.uuid4()),
                "is_default_name": True,
                "name": "text",
                "segments": segments,
                "type": "text",
            }
        ],
        "update_time": 0,
        "version": 360000,
    }


def _draft_meta_info(draft_id: str, draft_name: str, total_us: int) -> dict:
    """Build the ``draft_meta_info.json`` metadata sidecar."""
    return {
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_materials": [],
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "",
            "draft_enterprise_id": "",
            "draft_enterprise_name": "",
            "enterprise_material": [],
        },
        "draft_fold_path": "",
        "draft_id": draft_id,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_materials": [
            {"type": 0, "value": []},
            {"type": 1, "value": []},
            {"type": 2, "value": []},
            {"type": 3, "value": []},
            {"type": 6, "value": []},
            {"type": 7, "value": []},
            {"type": 8, "value": []},
        ],
        "draft_materials_copied_info": [],
        "draft_name": draft_name,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": "",
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": 0,
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": 0,
        "tm_draft_modified": 0,
        "tm_draft_removed": 0,
        "tm_duration": total_us,
    }


def export_capcut(
    result: TranscriptionResult,
    media_name: str = "video",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    font_size: float = 15.0,
    font_color: str = "#FFFFFF",
    draft_name: str | None = None,
) -> bytes:
    """Serialize a TranscriptionResult as a CapCut draft ZIP (bytes).

    The ZIP contains ``<draft_name>/draft_content.json``,
    ``<draft_name>/draft_info.json`` and ``<draft_name>/draft_meta_info.json``.
    ``draft_name`` defaults to ``media_name`` (sanitized for use as a folder
    name). Raises ExportError on non-positive dimensions/fps/font_size or a
    malformed ``#RRGGBB`` font_color.
    """
    if width <= 0 or height <= 0 or fps <= 0 or font_size <= 0:
        raise ExportError("width, height, fps and font_size must be positive")
    if not isinstance(font_color, str) or not _HEX_COLOR.match(font_color):
        raise ExportError(f"Invalid CapCut font_color {font_color!r}: expected #RRGGBB")

    name = _safe_draft_name(draft_name or media_name)
    draft_id = str(uuid.uuid4())
    content = _draft_content(result, draft_id, name, width, height, fps, font_size, font_color)
    meta = _draft_meta_info(draft_id, name, content["duration"])

    project_json = json.dumps(content, ensure_ascii=False, indent=4)
    meta_json = json.dumps(meta, ensure_ascii=False, indent=4)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}/draft_content.json", project_json)
        zf.writestr(f"{name}/draft_info.json", project_json)
        zf.writestr(f"{name}/draft_meta_info.json", meta_json)
    return buf.getvalue()
