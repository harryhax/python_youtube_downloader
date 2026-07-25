#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from yt_dlp import YoutubeDL


DEFAULT_CONFIG = {
    "defaults": {
        "output_dir": "downloads",
        "caption_langs": ["en", "en-orig"],
        "all_captions": False,
        "video_format": "bestvideo+bestaudio/best",
        "fallback_video_formats": ["best[ext=mp4]", "best"],
        "live_video_format": "best[ext=mp4]/best",
        "live_fallback_video_formats": ["best", "worst[ext=mp4]/worst"],
        "retries_per_format": 2,
        "merge_output_format": "mp4",
        "video_encoder": "h264_videotoolbox",
        "fallback_video_encoder": "libx264",
        "auto_edit": False,
        "speech_padding_seconds": 2.5,
        "silence_threshold_db": -35,
        "min_silence_duration": 0.7,
        "min_speech_duration": 0.2,
        "auto_edit_max_input_minutes": None,
        "caption_auto_edit_audit": False,
        "funny_caption_model": "google/flan-t5-small",
        "funny_caption_score_threshold": 3.5,
        "funny_caption_window_max_gap_seconds": 1.0,
        "funny_caption_window_max_duration_seconds": 12.0,
        "funny_caption_window_min_chars": 20,
        "funny_caption_max_new_tokens": 16,
        "funny_caption_audit": True,
        "auto_edit_suffix": "_truncated",
        "friendly_errors": True,
    },
    "error_messages": {
        "invalid_url": "The URL could not be read as a valid YouTube video link.",
        "http_403": "YouTube blocked this video stream request (HTTP 403). Try again later, update yt-dlp, or change video format in config.",
        "http_429": "Too many requests (HTTP 429). Wait a bit and try again.",
        "ffmpeg_missing": "ffmpeg is not installed or not on PATH. Install ffmpeg to enable clip export.",
        "ffprobe_missing": "ffprobe is not installed or not on PATH. Install ffmpeg to enable auto-edit.",
        "invalid_time_range": "End time must be greater than start time.",
        "invalid_time_format": "Time must be SS, MM:SS, or HH:MM:SS.",
        "no_speech_segments": "No talking segments were detected with current silence settings.",
        "no_caption_segments": "No caption segments were detected with current caption settings.",
        "no_funny_segments": "No funny caption segments were detected with current settings.",
        "captions_not_found": "No downloaded caption file was found for caption-based auto-edit.",
        "captions_failed": "Captions could not be downloaded. Continuing with video only.",
        "transformers_missing": "Install transformers/torch to enable local funny-caption editing.",
        "generic": "The download failed. Please try again in a moment.",
    },
}


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_CONFIG

    with path.open("r", encoding="utf-8") as f:
        user_config = json.load(f)

    merged = {
        "defaults": {**DEFAULT_CONFIG["defaults"], **user_config.get("defaults", {})},
        "error_messages": {
            **DEFAULT_CONFIG["error_messages"],
            **user_config.get("error_messages", {}),
        },
    }
    return merged


def friendly_error_message(exc: Exception, error_messages: dict) -> str:
    message = str(exc).lower()
    if "could not extract a youtube video id" in message:
        return error_messages["invalid_url"]
    if "time must be in hh:mm:ss" in message:
        return error_messages["invalid_time_format"]
    if "end time must be greater than start time" in message:
        return error_messages["invalid_time_range"]
    if "ffmpeg is not installed" in message:
        return error_messages["ffmpeg_missing"]
    if "ffprobe is not installed" in message:
        return error_messages["ffprobe_missing"]
    if "http error 429" in message:
        return error_messages["http_429"]
    if "http error 403" in message:
        return error_messages["http_403"]
    if "no talking segments were detected" in message:
        return error_messages["no_speech_segments"]
    if "no caption segments were detected" in message:
        return error_messages["no_caption_segments"]
    if "no funny caption segments were detected" in message:
        return error_messages.get("no_funny_segments", "No funny caption segments were detected.")
    if "could not locate downloaded caption file" in message:
        return error_messages["captions_not_found"]
    if "transformers is not installed" in message:
        return error_messages.get(
            "transformers_missing",
            "Install transformers/torch to enable local funny-caption editing.",
        )
    return f"{error_messages['generic']} ({exc})"


def parse_time_to_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) not in (1, 2, 3):
        raise ValueError("Time must be in HH:MM:SS, MM:SS, or SS format")

    parts = [int(part) for part in parts]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds


def sanitize_path_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or "video"


def normalize_url(url: str) -> str:
    # Accept URLs pasted with shell-escaped query separators, e.g. \?feature\=share.
    replacements = {
        r"\?": "?",
        r"\&": "&",
        r"\=": "=",
    }
    normalized = url.strip()
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def is_retryable_download_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "http error 403" in message or "http error 429" in message


def get_video_duration_seconds(video_path: Path) -> float:
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        raise RuntimeError("ffprobe is not installed or not available on PATH")

    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def detect_silence_segments(
    video_path: Path,
    silence_threshold_db: float,
    min_silence_duration: float,
    analysis_limit_seconds: float | None = None,
) -> list[tuple[float, float | None]]:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is not installed or not available on PATH")

    command = [
        ffmpeg_path,
        "-hide_banner",
    ]
    if analysis_limit_seconds is not None:
        command.extend(["-t", f"{analysis_limit_seconds:.3f}"])
    command.extend(
        [
            "-i",
            str(video_path),
            "-af",
            f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_duration}",
            "-f",
            "null",
            "-",
        ]
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    output = f"{result.stdout}\n{result.stderr}"
    silences: list[tuple[float, float | None]] = []
    pending_start: float | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            pending_start = float(start_match.group(1))
            continue

        end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if end_match and pending_start is not None:
            silences.append((pending_start, float(end_match.group(1))))
            pending_start = None

    if pending_start is not None:
        silences.append((pending_start, None))

    return silences


def build_talking_segments(
    duration_seconds: float,
    silence_segments: list[tuple[float, float | None]],
    padding_seconds: float,
    min_speech_duration: float,
) -> list[tuple[float, float]]:
    completed_silences: list[tuple[float, float]] = []
    for start, end in silence_segments:
        resolved_end = duration_seconds if end is None else min(end, duration_seconds)
        if resolved_end > start:
            completed_silences.append((max(0.0, start), resolved_end))

    completed_silences.sort(key=lambda item: item[0])

    speech_segments: list[tuple[float, float]] = []
    cursor = 0.0
    for silence_start, silence_end in completed_silences:
        if silence_start > cursor:
            speech_segments.append((cursor, silence_start))
        cursor = max(cursor, silence_end)

    if cursor < duration_seconds:
        speech_segments.append((cursor, duration_seconds))

    return pad_and_merge_segments(
        speech_segments,
        duration_seconds,
        padding_seconds,
        min_speech_duration,
    )


def pad_and_merge_segments(
    segments: list[tuple[float, float]],
    duration_seconds: float,
    padding_seconds: float,
    min_segment_duration: float,
) -> list[tuple[float, float]]:
    padded_segments: list[tuple[float, float]] = []
    for start, end in segments:
        padded_start = max(0.0, start - padding_seconds)
        padded_end = min(duration_seconds, end + padding_seconds)
        if padded_end - padded_start >= min_segment_duration:
            padded_segments.append((padded_start, padded_end))

    if not padded_segments:
        return []

    merged_segments = [padded_segments[0]]
    for start, end in padded_segments[1:]:
        last_start, last_end = merged_segments[-1]
        if start <= last_end:
            merged_segments[-1] = (last_start, max(last_end, end))
        else:
            merged_segments.append((start, end))

    return merged_segments


def render_video_segments(
    input_path: Path,
    output_path: Path,
    segments: list[tuple[float, float]],
    input_limit_seconds: float | None = None,
    video_encoder: str = "h264_videotoolbox",
    fallback_video_encoder: str = "libx264",
) -> tuple[int, float]:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is not installed or not available on PATH")

    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    total_kept_seconds = 0.0
    for index, (start, end) in enumerate(segments):
        total_kept_seconds += end - start
        filter_parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]"
        )
        filter_parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")

    filter_parts.append(
        f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[v][a]"
    )
    filter_complex = ";".join(filter_parts)

    command = [
        ffmpeg_path,
        "-y",
    ]
    if input_limit_seconds is not None:
        command.extend(["-t", f"{input_limit_seconds:.3f}"])
    command.extend(
        [
            "-i",
            str(input_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            video_encoder,
            "-c:a",
            "aac",
            str(output_path),
        ]
    )

    try:
        subprocess.run(
            command,
            check=True,
        )
    except subprocess.CalledProcessError:
        fallback_command = command.copy()
        codec_index = fallback_command.index("-c:v") + 1
        fallback_command[codec_index] = fallback_video_encoder
        print(
            f"Video encoder '{video_encoder}' unavailable, "
            f"falling back to '{fallback_video_encoder}'."
        )
        subprocess.run(
            fallback_command,
            check=True,
        )

    return len(segments), total_kept_seconds


def parse_vtt_timestamp(value: str) -> float:
    cleaned = value.strip().split()[0].replace(",", ".")
    parts = cleaned.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    raise ValueError(f"Unsupported VTT timestamp: {value}")


def format_seconds_as_timestamp(value: float) -> str:
    total_ms = max(0, int(round(value * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    milliseconds = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def extract_raw_caption_segments(
    caption_path: Path,
    duration_seconds: float,
    source_start_offset_seconds: float = 0.0,
) -> list[tuple[float, float]]:
    lines = caption_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    raw_segments: list[tuple[float, float]] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue

        start_text, end_text = [part.strip() for part in line.split("-->", 1)]
        cue_start = parse_vtt_timestamp(start_text)
        cue_end = parse_vtt_timestamp(end_text)

        index += 1
        cue_text: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_line = lines[index].strip()
            if not cue_line.isdigit():
                cue_text.append(cue_line)
            index += 1

        adjusted_start = max(0.0, cue_start - source_start_offset_seconds)
        adjusted_end = min(duration_seconds, cue_end - source_start_offset_seconds)
        if cue_text and adjusted_end > adjusted_start and adjusted_start < duration_seconds:
            raw_segments.append((adjusted_start, adjusted_end))

        index += 1

    return raw_segments


def extract_caption_cues_with_text(
    caption_path: Path,
    duration_seconds: float,
    source_start_offset_seconds: float = 0.0,
) -> list[dict]:
    lines = caption_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    cues: list[dict] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue

        start_text, end_text = [part.strip() for part in line.split("-->", 1)]
        cue_start = parse_vtt_timestamp(start_text)
        cue_end = parse_vtt_timestamp(end_text)

        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_line = lines[index].strip()
            if not cue_line.isdigit():
                # Remove simple VTT tags for cleaner LLM input.
                cue_lines.append(re.sub(r"<[^>]+>", "", cue_line))
            index += 1

        adjusted_start = max(0.0, cue_start - source_start_offset_seconds)
        adjusted_end = min(duration_seconds, cue_end - source_start_offset_seconds)
        cue_text = " ".join(cue_lines).strip()
        if cue_text and adjusted_end > adjusted_start and adjusted_start < duration_seconds:
            cues.append(
                {
                    "start": adjusted_start,
                    "end": adjusted_end,
                    "text": cue_text,
                }
            )

        index += 1

    return cues


def build_caption_text_windows(
    cues: list[dict],
    max_gap_seconds: float,
    max_window_seconds: float,
    min_chars: int,
) -> list[dict]:
    if not cues:
        return []

    windows: list[dict] = []
    current_start = cues[0]["start"]
    current_end = cues[0]["end"]
    current_text_parts = [cues[0]["text"]]

    for cue in cues[1:]:
        gap = cue["start"] - current_end
        proposed_duration = cue["end"] - current_start
        can_extend = gap <= max_gap_seconds and proposed_duration <= max_window_seconds

        if can_extend:
            current_end = cue["end"]
            current_text_parts.append(cue["text"])
            continue

        current_text = " ".join(current_text_parts).strip()
        if len(current_text) >= min_chars:
            windows.append(
                {
                    "start": current_start,
                    "end": current_end,
                    "text": current_text,
                }
            )

        current_start = cue["start"]
        current_end = cue["end"]
        current_text_parts = [cue["text"]]

    current_text = " ".join(current_text_parts).strip()
    if len(current_text) >= min_chars:
        windows.append(
            {
                "start": current_start,
                "end": current_end,
                "text": current_text,
            }
        )

    return windows


def parse_funny_score(text: str) -> float:
    match = re.search(r"\b([0-5](?:\.[0-9]+)?)\b", text)
    if not match:
        return 0.0
    return float(match.group(1))


def score_caption_windows_with_hf(
    windows: list[dict],
    model_name: str,
    max_new_tokens: int,
) -> list[dict]:
    if not windows:
        return []

    try:
        from transformers import pipeline
    except Exception as exc:
        raise RuntimeError("transformers is not installed") from exc

    scorer = pipeline("text2text-generation", model=model_name)
    scored_windows: list[dict] = []

    for window in windows:
        prompt = (
            "Rate how funny this caption excerpt is from 0 to 5. "
            "Return only a number.\n\n"
            f"Caption excerpt:\n{window['text']}\n\n"
            "Score:"
        )
        result = scorer(
            prompt,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            truncation=True,
        )
        raw_output = str(result[0].get("generated_text", "")).strip()
        score = parse_funny_score(raw_output)
        scored_windows.append(
            {
                **window,
                "score": score,
                "raw_model_output": raw_output,
            }
        )

    return scored_windows


def print_funny_caption_audit_report(
    scored_windows: list[dict],
    threshold: float,
) -> None:
    if not scored_windows:
        print("\nFunny Caption Scoring: no windows were available for scoring.")
        return

    kept = [item for item in scored_windows if item["score"] >= threshold]
    print("\nFunny Caption Scoring")
    print(f"- Total scored windows: {len(scored_windows)}")
    print(f"- Funny score threshold: {threshold:.2f}")
    print(f"- Windows selected: {len(kept)}")

    top_rows = sorted(scored_windows, key=lambda item: item["score"], reverse=True)[:10]
    print("- Top scored windows:")
    for idx, item in enumerate(top_rows, start=1):
        preview = item["text"].replace("\n", " ").strip()
        if len(preview) > 90:
            preview = f"{preview[:87]}..."
        print(
            f"  {idx:02d}. {format_seconds_as_timestamp(item['start'])} -> "
            f"{format_seconds_as_timestamp(item['end'])} | score={item['score']:.2f} | {preview}"
        )


def auto_edit_video_from_funny_captions(
    input_path: Path,
    caption_path: Path,
    output_path: Path,
    padding_seconds: float,
    min_segment_duration: float,
    funny_model_name: str,
    funny_score_threshold: float,
    funny_window_max_gap_seconds: float,
    funny_window_max_duration_seconds: float,
    funny_window_min_chars: int,
    funny_max_new_tokens: int,
    max_input_minutes: float | None = None,
    source_start_offset_seconds: float = 0.0,
    funny_audit: bool = False,
    video_encoder: str = "h264_videotoolbox",
    fallback_video_encoder: str = "libx264",
) -> tuple[int, float, float]:
    duration_seconds = get_video_duration_seconds(input_path)
    if max_input_minutes is not None:
        if max_input_minutes <= 0:
            raise ValueError("max_input_minutes must be greater than 0")
        duration_seconds = min(duration_seconds, max_input_minutes * 60)

    print(
        f"Funny-caption auto-edit processing window: {duration_seconds:.1f}s "
        f"({'full video' if max_input_minutes is None else f'capped to {max_input_minutes:g} min'})"
    )

    raw_caption_segments = extract_raw_caption_segments(
        caption_path,
        duration_seconds,
        source_start_offset_seconds,
    )
    old_timeline_segments = pad_and_merge_segments(
        raw_caption_segments,
        duration_seconds,
        0.0,
        0.0,
    )

    cues = extract_caption_cues_with_text(
        caption_path,
        duration_seconds,
        source_start_offset_seconds,
    )
    windows = build_caption_text_windows(
        cues,
        funny_window_max_gap_seconds,
        funny_window_max_duration_seconds,
        funny_window_min_chars,
    )
    scored_windows = score_caption_windows_with_hf(
        windows,
        funny_model_name,
        funny_max_new_tokens,
    )

    funny_raw_segments = [
        (item["start"], item["end"])
        for item in scored_windows
        if item["score"] >= funny_score_threshold
    ]
    funny_segments = pad_and_merge_segments(
        funny_raw_segments,
        duration_seconds,
        padding_seconds,
        min_segment_duration,
    )

    if not funny_segments:
        raise RuntimeError("No funny caption segments were detected with current settings")

    segment_count, total_kept_seconds = render_video_segments(
        input_path,
        output_path,
        funny_segments,
        duration_seconds,
        video_encoder,
        fallback_video_encoder,
    )

    if funny_audit:
        print_caption_audit_report(
            caption_path,
            old_timeline_segments,
            funny_segments,
            duration_seconds,
        )
        print_funny_caption_audit_report(scored_windows, funny_score_threshold)

    return segment_count, total_kept_seconds, duration_seconds


def print_caption_audit_report(
    caption_path: Path,
    old_timeline_segments: list[tuple[float, float]],
    new_timeline_segments: list[tuple[float, float]],
    total_duration_seconds: float,
) -> None:
    kept_seconds = sum(end - start for start, end in new_timeline_segments)
    removed_seconds = max(0.0, total_duration_seconds - kept_seconds)
    kept_percent = (kept_seconds / total_duration_seconds * 100) if total_duration_seconds > 0 else 0
    cut_count = max(0, len(new_timeline_segments) - 1)

    def print_segment_block(title: str, segments: list[tuple[float, float]]) -> None:
        print(title)
        if not segments:
            print("  (none)")
            return

        max_rows = 25
        for idx, (start, end) in enumerate(segments[:max_rows], start=1):
            print(
                f"  {idx:02d}. {format_seconds_as_timestamp(start)} -> "
                f"{format_seconds_as_timestamp(end)} ({end - start:.2f}s)"
            )
        hidden = len(segments) - max_rows
        if hidden > 0:
            print(f"  ... {hidden} more segments omitted")

    print("\nCaption Auto-Edit Audit")
    print(f"- Caption file: {caption_path}")
    print(f"- Original timeline segments: {len(old_timeline_segments)}")
    print(f"- New timeline segments: {len(new_timeline_segments)}")
    print(f"- Cuts made: {cut_count}")
    print(f"- Total input duration: {total_duration_seconds:.2f}s")
    print(f"- Kept duration: {kept_seconds:.2f}s ({kept_percent:.1f}%)")
    print(f"- Removed duration: {removed_seconds:.2f}s ({100 - kept_percent:.1f}%)")

    print_segment_block("- Old timeline (caption cue windows):", old_timeline_segments)
    print_segment_block("- New timeline (after padding + merge):", new_timeline_segments)


def extract_caption_segments(
    caption_path: Path,
    duration_seconds: float,
    padding_seconds: float,
    min_segment_duration: float,
    source_start_offset_seconds: float = 0.0,
) -> list[tuple[float, float]]:
    raw_segments = extract_raw_caption_segments(
        caption_path,
        duration_seconds,
        source_start_offset_seconds,
    )

    return pad_and_merge_segments(
        raw_segments,
        duration_seconds,
        padding_seconds,
        min_segment_duration,
    )


def auto_edit_video(
    input_path: Path,
    output_path: Path,
    silence_threshold_db: float,
    min_silence_duration: float,
    padding_seconds: float,
    min_speech_duration: float,
    max_input_minutes: float | None = None,
    video_encoder: str = "h264_videotoolbox",
    fallback_video_encoder: str = "libx264",
) -> tuple[int, float, float]:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is not installed or not available on PATH")

    duration_seconds = get_video_duration_seconds(input_path)
    if max_input_minutes is not None:
        if max_input_minutes <= 0:
            raise ValueError("max_input_minutes must be greater than 0")
        duration_seconds = min(duration_seconds, max_input_minutes * 60)

    print(
        f"Auto-edit processing window: {duration_seconds:.1f}s "
        f"({'full video' if max_input_minutes is None else f'capped to {max_input_minutes:g} min'})"
    )

    silence_segments = detect_silence_segments(
        input_path,
        silence_threshold_db,
        min_silence_duration,
        duration_seconds,
    )
    talking_segments = build_talking_segments(
        duration_seconds,
        silence_segments,
        padding_seconds,
        min_speech_duration,
    )

    if not talking_segments:
        raise RuntimeError("No talking segments were detected with current silence settings")

    segment_count, total_kept_seconds = render_video_segments(
        input_path,
        output_path,
        talking_segments,
        duration_seconds,
        video_encoder,
        fallback_video_encoder,
    )

    return segment_count, total_kept_seconds, duration_seconds


def find_downloaded_video_file(video_output_path: Path, video_id: str, preferred_ext: str) -> Path:
    preferred_path = video_output_path / f"{video_id}.{preferred_ext}"
    if preferred_path.exists():
        return preferred_path

    candidates = sorted(
        [
            path
            for path in video_output_path.glob(f"{video_id}.*")
            if path.suffix.lower() not in {".vtt", ".srt", ".ass", ".json"}
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("Could not locate downloaded video file for post-processing")
    return candidates[0]


def find_downloaded_caption_file(
    video_output_path: Path,
    video_id: str,
    preferred_langs: list[str],
) -> Path:
    candidates = sorted(video_output_path.glob(f"{video_id}*.vtt"))
    if not candidates:
        raise RuntimeError("Could not locate downloaded caption file for caption-based auto-edit")

    for preferred_lang in preferred_langs:
        suffix = f".{preferred_lang}.vtt"
        for candidate in candidates:
            if candidate.name.endswith(suffix):
                return candidate

    return candidates[0]


def auto_edit_video_from_captions(
    input_path: Path,
    caption_path: Path,
    output_path: Path,
    padding_seconds: float,
    min_segment_duration: float,
    max_input_minutes: float | None = None,
    source_start_offset_seconds: float = 0.0,
    caption_audit: bool = False,
    video_encoder: str = "h264_videotoolbox",
    fallback_video_encoder: str = "libx264",
) -> tuple[int, float, float]:
    duration_seconds = get_video_duration_seconds(input_path)
    if max_input_minutes is not None:
        if max_input_minutes <= 0:
            raise ValueError("max_input_minutes must be greater than 0")
        duration_seconds = min(duration_seconds, max_input_minutes * 60)

    print(
        f"Caption-based auto-edit processing window: {duration_seconds:.1f}s "
        f"({'full video' if max_input_minutes is None else f'capped to {max_input_minutes:g} min'})"
    )

    raw_caption_segments = extract_raw_caption_segments(
        caption_path,
        duration_seconds,
        source_start_offset_seconds,
    )
    old_timeline_segments = pad_and_merge_segments(
        raw_caption_segments,
        duration_seconds,
        0.0,
        0.0,
    )
    caption_segments = pad_and_merge_segments(
        raw_caption_segments,
        duration_seconds,
        padding_seconds,
        min_segment_duration,
    )
    if not caption_segments:
        raise RuntimeError("No caption segments were detected with current caption settings")

    segment_count, total_kept_seconds = render_video_segments(
        input_path,
        output_path,
        caption_segments,
        duration_seconds,
        video_encoder,
        fallback_video_encoder,
    )
    if caption_audit:
        print_caption_audit_report(
            caption_path,
            old_timeline_segments,
            caption_segments,
            duration_seconds,
        )
    return segment_count, total_kept_seconds, duration_seconds


def audit_caption_timeline_only(
    input_path: Path,
    caption_path: Path,
    padding_seconds: float,
    min_segment_duration: float,
    max_input_minutes: float | None = None,
    source_start_offset_seconds: float = 0.0,
) -> tuple[int, float, float]:
    duration_seconds = get_video_duration_seconds(input_path)
    if max_input_minutes is not None:
        if max_input_minutes <= 0:
            raise ValueError("max_input_minutes must be greater than 0")
        duration_seconds = min(duration_seconds, max_input_minutes * 60)

    print(
        f"Caption audit processing window: {duration_seconds:.1f}s "
        f"({'full video' if max_input_minutes is None else f'capped to {max_input_minutes:g} min'})"
    )

    raw_caption_segments = extract_raw_caption_segments(
        caption_path,
        duration_seconds,
        source_start_offset_seconds,
    )
    old_timeline_segments = pad_and_merge_segments(
        raw_caption_segments,
        duration_seconds,
        0.0,
        0.0,
    )
    new_timeline_segments = pad_and_merge_segments(
        raw_caption_segments,
        duration_seconds,
        padding_seconds,
        min_segment_duration,
    )
    if not new_timeline_segments:
        raise RuntimeError("No caption segments were detected with current caption settings")

    print_caption_audit_report(
        caption_path,
        old_timeline_segments,
        new_timeline_segments,
        duration_seconds,
    )

    kept_seconds = sum(end - start for start, end in new_timeline_segments)
    return len(new_timeline_segments), kept_seconds, duration_seconds


def download_video(
    url: str,
    output_dir: str,
    start: str | None = None,
    end: str | None = None,
    caption_langs: list[str] | None = None,
    all_captions: bool = False,
    video_format: str = "bestvideo+bestaudio/best",
    fallback_video_formats: list[str] | None = None,
    live_video_format: str | None = None,
    live_fallback_video_formats: list[str] | None = None,
    retries_per_format: int = 2,
    merge_output_format: str = "mp4",
    auto_edit: bool = False,
    caption_based_auto_edit: bool = False,
    funny_caption_auto_edit: bool = False,
    speech_padding_seconds: float = 2.5,
    silence_threshold_db: float = -35,
    min_silence_duration: float = 0.7,
    min_speech_duration: float = 0.2,
    auto_edit_max_input_minutes: float | None = None,
    caption_auto_edit_audit: bool = False,
    funny_caption_model: str = "google/flan-t5-small",
    funny_caption_score_threshold: float = 3.5,
    funny_caption_window_max_gap_seconds: float = 1.0,
    funny_caption_window_max_duration_seconds: float = 12.0,
    funny_caption_window_min_chars: int = 20,
    funny_caption_max_new_tokens: int = 16,
    funny_caption_audit: bool = True,
    auto_edit_suffix: str = "_truncated",
    caption_failure_message: str = "Captions could not be downloaded. Continuing with video only.",
    video_encoder: str = "h264_videotoolbox",
    fallback_video_encoder: str = "libx264",
) -> None:
    url = normalize_url(url)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Fetch metadata first so we can create a stable per-video folder name.
    with YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info.get("id")
    title = info.get("title", "video")
    live_status = str(info.get("live_status", "")).lower()
    is_live_like = bool(info.get("is_live")) or live_status in {
        "is_live",
        "is_upcoming",
        "post_live",
    }
    if not video_id:
        raise ValueError("Could not extract a YouTube video ID from the URL")

    safe_title = sanitize_path_component(title)
    folder_name = f"{safe_title}_{video_id}"
    video_output_path = output_path / folder_name
    video_output_path.mkdir(parents=True, exist_ok=True)

    subtitle_langs = ["all"] if all_captions else (caption_langs or ["en", "en-orig"])

    selected_video_format = video_format
    selected_fallback_formats = fallback_video_formats or []
    if is_live_like:
        selected_video_format = live_video_format or video_format
        selected_fallback_formats = live_fallback_video_formats or selected_fallback_formats
        print("Detected live URL. Using live-video fallback strategy.")

    base_video_opts = {
        "outtmpl": str(video_output_path / f"{video_id}.%(ext)s"),
        "noplaylist": True,
        "merge_output_format": merge_output_format,
        "quiet": False,
    }

    format_candidates = [selected_video_format]
    for fallback in selected_fallback_formats:
        if fallback and fallback not in format_candidates:
            format_candidates.append(fallback)

    if retries_per_format < 1:
        retries_per_format = 1

    last_video_error: Exception | None = None
    chosen_format = selected_video_format
    video_downloaded = False

    for current_format in format_candidates:
        for attempt in range(1, retries_per_format + 1):
            try:
                print(
                    f"Downloading video (format: {current_format}, attempt {attempt}/{retries_per_format})"
                )
                video_opts = {**base_video_opts, "format": current_format}
                with YoutubeDL(video_opts) as ydl:
                    ydl.download([url])
                chosen_format = current_format
                video_downloaded = True
                break
            except Exception as exc:
                last_video_error = exc
                if is_retryable_download_error(exc) and attempt < retries_per_format:
                    print(f"Video download failed ({exc}). Retrying...")
                    continue

                print(f"Video download attempt failed ({exc}).")

        if video_downloaded:
            break

    if not video_downloaded and last_video_error is not None:
        raise last_video_error

    input_video_path = find_downloaded_video_file(video_output_path, video_id, merge_output_format)

    caption_opts = {
        **base_video_opts,
        "format": chosen_format,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": subtitle_langs,
        "subtitlesformat": "vtt/best",
    }

    try:
        with YoutubeDL(caption_opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        print(f"{caption_failure_message} ({exc})")

    post_process_input_path = input_video_path
    clip_start_seconds = 0.0

    if start is not None and end is not None:
        start_seconds = parse_time_to_seconds(start)
        end_seconds = parse_time_to_seconds(end)
        duration = max(0, end_seconds - start_seconds)
        if duration <= 0:
            raise ValueError("End time must be greater than start time")

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg is not installed or not available on PATH")

        input_path = post_process_input_path
        output_path_clip = video_output_path / f"{safe_title}_clip.mp4"
        clip_command = [
            ffmpeg_path,
            "-y",
            "-ss",
            str(start_seconds),
            "-i",
            str(input_path),
            "-t",
            str(duration),
            "-c:v",
            video_encoder,
            "-c:a",
            "aac",
            str(output_path_clip),
        ]
        try:
            subprocess.run(
                clip_command,
                check=True,
            )
        except subprocess.CalledProcessError:
            fallback_clip_command = clip_command.copy()
            codec_index = fallback_clip_command.index("-c:v") + 1
            fallback_clip_command[codec_index] = fallback_video_encoder
            print(
                f"Video encoder '{video_encoder}' unavailable, "
                f"falling back to '{fallback_video_encoder}'."
            )
            subprocess.run(
                fallback_clip_command,
                check=True,
            )
        print(f"Downloaded clip: {output_path_clip}")
        post_process_input_path = output_path_clip
        clip_start_seconds = float(start_seconds)
    else:
        print(f"Downloaded: {title}")

    if auto_edit:
        truncated_output_path = video_output_path / f"{safe_title}{auto_edit_suffix}.mp4"
        segment_count, kept_seconds, total_seconds = auto_edit_video(
            post_process_input_path,
            truncated_output_path,
            silence_threshold_db,
            min_silence_duration,
            speech_padding_seconds,
            min_speech_duration,
            auto_edit_max_input_minutes,
            video_encoder,
            fallback_video_encoder,
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            f"Auto-edited video created: {truncated_output_path} "
            f"(kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments, {percent_kept:.1f}%)"
        )

    if caption_based_auto_edit:
        caption_path = find_downloaded_caption_file(video_output_path, video_id, subtitle_langs)
        truncated_output_path = video_output_path / f"{safe_title}{auto_edit_suffix}_captions.mp4"
        segment_count, kept_seconds, total_seconds = auto_edit_video_from_captions(
            post_process_input_path,
            caption_path,
            truncated_output_path,
            speech_padding_seconds,
            min_speech_duration,
            auto_edit_max_input_minutes,
            clip_start_seconds,
            caption_auto_edit_audit,
            video_encoder,
            fallback_video_encoder,
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            f"Caption-based auto-edited video created: {truncated_output_path} "
            f"(kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments, {percent_kept:.1f}%)"
        )

    if funny_caption_auto_edit:
        caption_path = find_downloaded_caption_file(video_output_path, video_id, subtitle_langs)
        truncated_output_path = video_output_path / f"{safe_title}{auto_edit_suffix}_funny.mp4"
        segment_count, kept_seconds, total_seconds = auto_edit_video_from_funny_captions(
            post_process_input_path,
            caption_path,
            truncated_output_path,
            speech_padding_seconds,
            min_speech_duration,
            funny_caption_model,
            funny_caption_score_threshold,
            funny_caption_window_max_gap_seconds,
            funny_caption_window_max_duration_seconds,
            funny_caption_window_min_chars,
            funny_caption_max_new_tokens,
            auto_edit_max_input_minutes,
            clip_start_seconds,
            funny_caption_audit,
            video_encoder,
            fallback_video_encoder,
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            f"Funny-caption auto-edited video created: {truncated_output_path} "
            f"(kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments, {percent_kept:.1f}%)"
        )

    print(f"Saved video and captions to: {video_output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a YouTube video from a URL")
    parser.add_argument("url", help="The YouTube video URL")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON file (default: config.json)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where the downloaded video will be saved",
    )
    parser.add_argument("--start", help="Start time for the clip (format: 00:00:10)")
    parser.add_argument("--end", help="End time for the clip (format: 00:00:20)")
    parser.add_argument(
        "--caption-langs",
        default=None,
        help="Comma-separated caption languages to download (default: en,en-orig)",
    )
    parser.add_argument(
        "--all-captions",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Download all available caption languages (may trigger rate limits)",
    )
    parser.add_argument(
        "--auto-edit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Automatically remove long no-talking sections and create a truncated video",
    )
    parser.add_argument(
        "--caption-based-auto-edit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Create a truncated video using caption timing instead of audio silence detection",
    )
    parser.add_argument(
        "--funny-caption-auto-edit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Create a truncated video using local Hugging Face funny-caption scoring",
    )
    parser.add_argument(
        "--caption-auto-edit-audit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Print audit details for caption-based auto-edit timelines and cuts",
    )
    parser.add_argument(
        "--speech-padding-seconds",
        type=float,
        default=None,
        help="Seconds to keep before and after detected talking segments",
    )
    parser.add_argument(
        "--silence-threshold-db",
        type=float,
        default=None,
        help="Silence threshold in dB for talking detection (for example -35)",
    )
    parser.add_argument(
        "--min-silence-duration",
        type=float,
        default=None,
        help="Minimum silence duration in seconds used for cut detection",
    )
    parser.add_argument(
        "--min-speech-duration",
        type=float,
        default=None,
        help="Discard detected talking segments shorter than this many seconds",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = load_config(args.config)
    defaults = config["defaults"]
    error_messages = config["error_messages"]

    output_dir = args.output_dir or defaults["output_dir"]
    if args.caption_langs:
        caption_langs = [lang.strip() for lang in args.caption_langs.split(",") if lang.strip()]
    else:
        caption_langs = defaults["caption_langs"]
    all_captions = defaults["all_captions"] if args.all_captions is None else args.all_captions
    auto_edit = defaults["auto_edit"] if args.auto_edit is None else args.auto_edit
    caption_based_auto_edit = (
        False if args.caption_based_auto_edit is None else args.caption_based_auto_edit
    )
    funny_caption_auto_edit = (
        False if args.funny_caption_auto_edit is None else args.funny_caption_auto_edit
    )
    caption_auto_edit_audit = (
        defaults.get("caption_auto_edit_audit", False)
        if args.caption_auto_edit_audit is None
        else args.caption_auto_edit_audit
    )
    speech_padding_seconds = (
        defaults["speech_padding_seconds"]
        if args.speech_padding_seconds is None
        else args.speech_padding_seconds
    )
    silence_threshold_db = (
        defaults["silence_threshold_db"]
        if args.silence_threshold_db is None
        else args.silence_threshold_db
    )
    min_silence_duration = (
        defaults["min_silence_duration"]
        if args.min_silence_duration is None
        else args.min_silence_duration
    )
    min_speech_duration = (
        defaults["min_speech_duration"]
        if args.min_speech_duration is None
        else args.min_speech_duration
    )

    try:
        download_video(
            args.url,
            output_dir,
            args.start,
            args.end,
            caption_langs,
            all_captions,
            defaults["video_format"],
            defaults["fallback_video_formats"],
            defaults["live_video_format"],
            defaults["live_fallback_video_formats"],
            defaults["retries_per_format"],
            defaults["merge_output_format"],
            auto_edit,
            caption_based_auto_edit,
            funny_caption_auto_edit,
            speech_padding_seconds,
            silence_threshold_db,
            min_silence_duration,
            min_speech_duration,
            defaults.get("auto_edit_max_input_minutes"),
            caption_auto_edit_audit,
            defaults.get("funny_caption_model", "google/flan-t5-small"),
            defaults.get("funny_caption_score_threshold", 3.5),
            defaults.get("funny_caption_window_max_gap_seconds", 1.0),
            defaults.get("funny_caption_window_max_duration_seconds", 12.0),
            defaults.get("funny_caption_window_min_chars", 20),
            defaults.get("funny_caption_max_new_tokens", 16),
            defaults.get("funny_caption_audit", True),
            defaults["auto_edit_suffix"],
            error_messages["captions_failed"],
            defaults.get("video_encoder", "h264_videotoolbox"),
            defaults.get("fallback_video_encoder", "libx264"),
        )
    except Exception as exc:
        if defaults["friendly_errors"]:
            print(f"Download failed: {friendly_error_message(exc, error_messages)}")
        else:
            print(f"Download failed: {exc}")
        sys.exit(1)
