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
        "friendly_errors": True,
    },
    "error_messages": {
        "invalid_url": "The URL could not be read as a valid YouTube video link.",
        "http_403": "YouTube blocked this video stream request (HTTP 403). Try again later, update yt-dlp, or change video format in config.",
        "http_429": "Too many requests (HTTP 429). Wait a bit and try again.",
        "ffmpeg_missing": "ffmpeg is not installed or not on PATH. Install ffmpeg to enable clip export.",
        "invalid_time_range": "End time must be greater than start time.",
        "invalid_time_format": "Time must be SS, MM:SS, or HH:MM:SS.",
        "captions_failed": "Captions could not be downloaded. Continuing with video only.",
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
    if "http error 429" in message:
        return error_messages["http_429"]
    if "http error 403" in message:
        return error_messages["http_403"]
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
    caption_failure_message: str = "Captions could not be downloaded. Continuing with video only.",
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

    if start is not None and end is not None:
        start_seconds = parse_time_to_seconds(start)
        end_seconds = parse_time_to_seconds(end)
        duration = max(0, end_seconds - start_seconds)
        if duration <= 0:
            raise ValueError("End time must be greater than start time")

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg is not installed or not available on PATH")

        input_path = video_output_path / f"{video_id}.mp4"
        output_path_clip = video_output_path / f"{safe_title}_clip.mp4"
        subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-ss",
                str(start_seconds),
                "-i",
                str(input_path),
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                str(output_path_clip),
            ],
            check=True,
        )
        print(f"Downloaded clip: {output_path_clip}")
    else:
        print(f"Downloaded: {title}")
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
            error_messages["captions_failed"],
        )
    except Exception as exc:
        if defaults["friendly_errors"]:
            print(f"Download failed: {friendly_error_message(exc, error_messages)}")
        else:
            print(f"Download failed: {exc}")
        sys.exit(1)
