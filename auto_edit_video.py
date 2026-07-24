#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from download_youtube_video import auto_edit_video, friendly_error_message, load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-edit a local video by removing long no-talking sections"
    )
    parser.add_argument("input", help="Path to input video file")
    parser.add_argument(
        "--output",
        default=None,
        help="Path to output truncated video (default: input + suffix from config)",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON file (default: config.json)",
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
    parser.add_argument(
        "--max-input-minutes",
        type=float,
        default=None,
        help="Only process up to this many minutes from the start of the input video",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    defaults = config["defaults"]
    error_messages = config["error_messages"]

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Auto-edit failed: input file not found: {input_path}")
        sys.exit(1)

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
    max_input_minutes = (
        defaults.get("auto_edit_max_input_minutes")
        if args.max_input_minutes is None
        else args.max_input_minutes
    )

    if args.output:
        output_path = Path(args.output)
    else:
        suffix = defaults.get("auto_edit_suffix", "_truncated")
        ext = input_path.suffix if input_path.suffix else ".mp4"
        output_path = input_path.with_name(f"{input_path.stem}{suffix}{ext}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        segment_count, kept_seconds, total_seconds = auto_edit_video(
            input_path,
            output_path,
            silence_threshold_db,
            min_silence_duration,
            speech_padding_seconds,
            min_speech_duration,
            max_input_minutes,
            defaults.get("video_encoder", "h264_videotoolbox"),
            defaults.get("fallback_video_encoder", "libx264"),
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            f"Auto-edited video created: {output_path} "
            f"(kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments, {percent_kept:.1f}%)"
        )
    except Exception as exc:
        if defaults["friendly_errors"]:
            print(f"Auto-edit failed: {friendly_error_message(exc, error_messages)}")
        else:
            print(f"Auto-edit failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
