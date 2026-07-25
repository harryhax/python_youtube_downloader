#!/usr/bin/env python3
from pathlib import Path

from download_youtube_video import (
    auto_edit_video,
    auto_edit_video_from_captions,
    auto_edit_video_from_funny_captions,
    audit_caption_timeline_only,
    download_video,
    friendly_error_message,
    load_config,
)


def prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else (default or "")


def prompt_bool(label: str, default: bool) -> bool:
    default_hint = "Y/n" if default else "y/N"
    value = input(f"{label} ({default_hint}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def prompt_float(label: str, default: float) -> float:
    raw = prompt_text(label, str(default))
    try:
        return float(raw)
    except ValueError:
        print(f"Invalid number '{raw}', using {default}.")
        return default


def prompt_optional_float(label: str, default: float | None = None) -> float | None:
    default_text = "none" if default is None else str(default)
    raw = prompt_text(label, default_text)
    if not raw or raw.lower() in {"none", "no", "n", "off", "0"}:
        return None
    try:
        value = float(raw)
    except ValueError:
        print("Invalid number, using no limit.")
        return None
    if value <= 0:
        print("Value must be greater than 0, using no limit.")
        return None
    return value


def list_download_video_files(downloads_dir: Path) -> list[Path]:
    if not downloads_dir.exists():
        return []

    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
    return sorted(
        [
            path
            for path in downloads_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in video_extensions
        ],
        key=lambda path: str(path).lower(),
    )


def prompt_download_video_file(downloads_dir: Path) -> Path | None:
    video_files = list_download_video_files(downloads_dir)
    if not video_files:
        print(f"No video files found under {downloads_dir}")
        manual_path = prompt_text("Path to local video file")
        return Path(manual_path) if manual_path else None

    print("Available video files in downloads:")
    for index, path in enumerate(video_files, start=1):
        print(f"{index}) {path.relative_to(downloads_dir.parent)}")
    print("M) Enter a path manually")

    choice = input("Select a file: ").strip().lower()
    if choice == "m":
        manual_path = prompt_text("Path to local video file")
        return Path(manual_path) if manual_path else None

    try:
        selected_index = int(choice)
    except ValueError:
        print("Invalid selection.")
        return None

    if 1 <= selected_index <= len(video_files):
        return video_files[selected_index - 1]

    print("Selection out of range.")
    return None


def list_download_caption_files(downloads_dir: Path) -> list[Path]:
    if not downloads_dir.exists():
        return []

    return sorted(
        [path for path in downloads_dir.rglob("*.vtt") if path.is_file()],
        key=lambda path: str(path).lower(),
    )


def prompt_download_caption_file(downloads_dir: Path) -> Path | None:
    caption_files = list_download_caption_files(downloads_dir)
    if not caption_files:
        print(f"No caption files found under {downloads_dir}")
        manual_path = prompt_text("Path to local caption file")
        return Path(manual_path) if manual_path else None

    print("Available caption files in downloads:")
    for index, path in enumerate(caption_files, start=1):
        print(f"{index}) {path.relative_to(downloads_dir.parent)}")
    print("M) Enter a path manually")

    choice = input("Select a caption file: ").strip().lower()
    if choice == "m":
        manual_path = prompt_text("Path to local caption file")
        return Path(manual_path) if manual_path else None

    try:
        selected_index = int(choice)
    except ValueError:
        print("Invalid selection.")
        return None

    if 1 <= selected_index <= len(caption_files):
        return caption_files[selected_index - 1]

    print("Selection out of range.")
    return None


def run_download_flow(
    defaults: dict,
    error_messages: dict,
    with_clip: bool,
    with_auto_edit: bool,
    with_caption_based_auto_edit: bool = False,
    with_funny_caption_auto_edit: bool = False,
) -> None:
    url = prompt_text("YouTube URL")
    output_dir = prompt_text("Output directory", defaults["output_dir"])

    start = None
    end = None
    if with_clip:
        start = prompt_text("Clip start time (HH:MM:SS, MM:SS, or SS)")
        end = prompt_text("Clip end time (HH:MM:SS, MM:SS, or SS)")

    caption_lang_default = ",".join(defaults["caption_langs"])
    caption_langs = [
        lang.strip()
        for lang in prompt_text("Caption languages comma-separated", caption_lang_default).split(",")
        if lang.strip()
    ]
    all_captions = prompt_bool("Download all caption languages", defaults["all_captions"])

    auto_edit = with_auto_edit or defaults["auto_edit"]
    speech_padding_seconds = defaults["speech_padding_seconds"]
    silence_threshold_db = defaults["silence_threshold_db"]
    min_silence_duration = defaults["min_silence_duration"]
    min_speech_duration = defaults["min_speech_duration"]
    auto_edit_max_input_minutes = defaults.get("auto_edit_max_input_minutes")
    caption_based_auto_edit = with_caption_based_auto_edit
    funny_caption_auto_edit = with_funny_caption_auto_edit
    caption_auto_edit_audit = defaults.get("caption_auto_edit_audit", False)
    funny_caption_audit = defaults.get("funny_caption_audit", True)

    if with_auto_edit or with_caption_based_auto_edit or with_funny_caption_auto_edit:
        speech_padding_seconds = prompt_float(
            "Padding seconds before and after kept segments",
            defaults["speech_padding_seconds"],
        )
        min_speech_duration = prompt_float(
            "Minimum kept segment duration seconds",
            defaults["min_speech_duration"],
        )
        auto_edit_max_input_minutes = prompt_optional_float(
            "Max input minutes for testing (set none for full video)",
            defaults.get("auto_edit_max_input_minutes"),
        )
    if with_caption_based_auto_edit:
        caption_auto_edit_audit = prompt_bool(
            "Show caption auto-edit audit report",
            defaults.get("caption_auto_edit_audit", False),
        )
    if with_funny_caption_auto_edit:
        funny_caption_audit = prompt_bool(
            "Show funny-caption audit report",
            defaults.get("funny_caption_audit", True),
        )
    if with_auto_edit:
        silence_threshold_db = prompt_float(
            "Silence threshold dB",
            defaults["silence_threshold_db"],
        )
        min_silence_duration = prompt_float(
            "Minimum silence duration seconds",
            defaults["min_silence_duration"],
        )

    try:
        download_video(
            url,
            output_dir,
            start,
            end,
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
            auto_edit_max_input_minutes,
            caption_auto_edit_audit,
            defaults.get("funny_caption_model", "google/flan-t5-small"),
            defaults.get("funny_caption_score_threshold", 3.5),
            defaults.get("funny_caption_window_max_gap_seconds", 1.0),
            defaults.get("funny_caption_window_max_duration_seconds", 12.0),
            defaults.get("funny_caption_window_min_chars", 20),
            defaults.get("funny_caption_max_new_tokens", 16),
            funny_caption_audit,
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


def run_auto_edit_only_flow(defaults: dict, error_messages: dict) -> None:
    input_path = prompt_download_video_file(Path(defaults["output_dir"]))
    if input_path is None:
        return
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    output_path_str = prompt_text("Output video path (leave blank for default)", "")
    if output_path_str:
        output_path = Path(output_path_str)
    else:
        ext = input_path.suffix if input_path.suffix else ".mp4"
        output_path = input_path.with_name(
            f"{input_path.stem}{defaults['auto_edit_suffix']}{ext}"
        )

    speech_padding_seconds = prompt_float(
        "Speech padding seconds",
        defaults["speech_padding_seconds"],
    )
    silence_threshold_db = prompt_float(
        "Silence threshold dB",
        defaults["silence_threshold_db"],
    )
    min_silence_duration = prompt_float(
        "Minimum silence duration seconds",
        defaults["min_silence_duration"],
    )
    min_speech_duration = prompt_float(
        "Minimum speech duration seconds",
        defaults["min_speech_duration"],
    )
    max_input_minutes = prompt_optional_float(
        "Max input minutes for testing (set none for full video)",
        defaults.get("auto_edit_max_input_minutes"),
    )

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


def run_caption_auto_edit_only_flow(defaults: dict, error_messages: dict) -> None:
    downloads_dir = Path(defaults["output_dir"])
    input_path = prompt_download_video_file(downloads_dir)
    if input_path is None:
        return
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    caption_path = prompt_download_caption_file(downloads_dir)
    if caption_path is None:
        return
    if not caption_path.exists():
        print(f"Caption file not found: {caption_path}")
        return

    output_path_str = prompt_text("Output video path (leave blank for default)", "")
    if output_path_str:
        output_path = Path(output_path_str)
    else:
        ext = input_path.suffix if input_path.suffix else ".mp4"
        output_path = input_path.with_name(
            f"{input_path.stem}{defaults['auto_edit_suffix']}_captions{ext}"
        )

    speech_padding_seconds = prompt_float(
        "Padding seconds before and after kept segments",
        defaults["speech_padding_seconds"],
    )
    min_speech_duration = prompt_float(
        "Minimum kept segment duration seconds",
        defaults["min_speech_duration"],
    )
    max_input_minutes = prompt_optional_float(
        "Max input minutes for testing (set none for full video)",
        defaults.get("auto_edit_max_input_minutes"),
    )
    caption_auto_edit_audit = prompt_bool(
        "Show caption auto-edit audit report",
        defaults.get("caption_auto_edit_audit", False),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        segment_count, kept_seconds, total_seconds = auto_edit_video_from_captions(
            input_path,
            caption_path,
            output_path,
            speech_padding_seconds,
            min_speech_duration,
            max_input_minutes,
            0.0,
            caption_auto_edit_audit,
            defaults.get("video_encoder", "h264_videotoolbox"),
            defaults.get("fallback_video_encoder", "libx264"),
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            f"Caption-based auto-edited video created: {output_path} "
            f"(kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments, {percent_kept:.1f}%)"
        )
    except Exception as exc:
        if defaults["friendly_errors"]:
            print(f"Caption-based auto-edit failed: {friendly_error_message(exc, error_messages)}")
        else:
            print(f"Caption-based auto-edit failed: {exc}")


def run_funny_caption_auto_edit_only_flow(defaults: dict, error_messages: dict) -> None:
    downloads_dir = Path(defaults["output_dir"])
    input_path = prompt_download_video_file(downloads_dir)
    if input_path is None:
        return
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    caption_path = prompt_download_caption_file(downloads_dir)
    if caption_path is None:
        return
    if not caption_path.exists():
        print(f"Caption file not found: {caption_path}")
        return

    output_path_str = prompt_text("Output video path (leave blank for default)", "")
    if output_path_str:
        output_path = Path(output_path_str)
    else:
        ext = input_path.suffix if input_path.suffix else ".mp4"
        output_path = input_path.with_name(
            f"{input_path.stem}{defaults['auto_edit_suffix']}_funny{ext}"
        )

    speech_padding_seconds = prompt_float(
        "Padding seconds before and after kept segments",
        defaults["speech_padding_seconds"],
    )
    min_speech_duration = prompt_float(
        "Minimum kept segment duration seconds",
        defaults["min_speech_duration"],
    )
    max_input_minutes = prompt_optional_float(
        "Max input minutes for testing (set none for full video)",
        defaults.get("auto_edit_max_input_minutes"),
    )
    funny_score_threshold = prompt_float(
        "Funny score threshold (0-5)",
        defaults.get("funny_caption_score_threshold", 3.5),
    )
    funny_caption_audit = prompt_bool(
        "Show funny-caption audit report",
        defaults.get("funny_caption_audit", True),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        segment_count, kept_seconds, total_seconds = auto_edit_video_from_funny_captions(
            input_path,
            caption_path,
            output_path,
            speech_padding_seconds,
            min_speech_duration,
            defaults.get("funny_caption_model", "google/flan-t5-small"),
            funny_score_threshold,
            defaults.get("funny_caption_window_max_gap_seconds", 1.0),
            defaults.get("funny_caption_window_max_duration_seconds", 12.0),
            defaults.get("funny_caption_window_min_chars", 20),
            defaults.get("funny_caption_max_new_tokens", 16),
            max_input_minutes,
            0.0,
            funny_caption_audit,
            defaults.get("video_encoder", "h264_videotoolbox"),
            defaults.get("fallback_video_encoder", "libx264"),
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            f"Funny-caption auto-edited video created: {output_path} "
            f"(kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments, {percent_kept:.1f}%)"
        )
    except Exception as exc:
        if defaults["friendly_errors"]:
            print(f"Funny-caption auto-edit failed: {friendly_error_message(exc, error_messages)}")
        else:
            print(f"Funny-caption auto-edit failed: {exc}")


def run_caption_audit_only_flow(defaults: dict, error_messages: dict) -> None:
    downloads_dir = Path(defaults["output_dir"])
    input_path = prompt_download_video_file(downloads_dir)
    if input_path is None:
        return
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return

    caption_path = prompt_download_caption_file(downloads_dir)
    if caption_path is None:
        return
    if not caption_path.exists():
        print(f"Caption file not found: {caption_path}")
        return

    speech_padding_seconds = prompt_float(
        "Padding seconds before and after kept segments",
        defaults["speech_padding_seconds"],
    )
    min_speech_duration = prompt_float(
        "Minimum kept segment duration seconds",
        defaults["min_speech_duration"],
    )
    max_input_minutes = prompt_optional_float(
        "Max input minutes for testing (set none for full video)",
        defaults.get("auto_edit_max_input_minutes"),
    )

    try:
        segment_count, kept_seconds, total_seconds = audit_caption_timeline_only(
            input_path,
            caption_path,
            speech_padding_seconds,
            min_speech_duration,
            max_input_minutes,
        )
        percent_kept = (kept_seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(
            "Caption audit completed (no video rendered). "
            f"Kept {kept_seconds:.1f}s / {total_seconds:.1f}s across {segment_count} segments ({percent_kept:.1f}%)."
        )
    except Exception as exc:
        if defaults["friendly_errors"]:
            print(f"Caption audit failed: {friendly_error_message(exc, error_messages)}")
        else:
            print(f"Caption audit failed: {exc}")


def main() -> None:
    config_path = prompt_text("Config path", "config.json")
    config = load_config(config_path)
    defaults = config["defaults"]
    error_messages = config["error_messages"]

    while True:
        print("\nVideo Tools Menu")
        print("\nDownload workflows")
        print("1) Download video + captions")
        print("2) Download video + captions + clip")
        print("3) Download video + captions + voice-based auto-edit")
        print("4) Download video + captions + caption-based auto-edit")
        print("5) Download video + captions + funny-caption auto-edit (local HF)")
        print("\nLocal file workflows")
        print("6) Voice-based auto-edit existing local video")
        print("7) Caption-based auto-edit existing local video")
        print("8) Funny-caption auto-edit existing local video (local HF)")
        print("9) Caption timeline audit (stats only, no edit)")
        print("\nOther")
        print("10) Exit")

        choice = input("Select an option: ").strip()
        if choice == "1":
            run_download_flow(defaults, error_messages, with_clip=False, with_auto_edit=False)
        elif choice == "2":
            run_download_flow(defaults, error_messages, with_clip=True, with_auto_edit=False)
        elif choice == "3":
            run_download_flow(defaults, error_messages, with_clip=False, with_auto_edit=True)
        elif choice == "4":
            run_download_flow(
                defaults,
                error_messages,
                with_clip=False,
                with_auto_edit=False,
                with_caption_based_auto_edit=True,
            )
        elif choice == "5":
            run_download_flow(
                defaults,
                error_messages,
                with_clip=False,
                with_auto_edit=False,
                with_caption_based_auto_edit=False,
                with_funny_caption_auto_edit=True,
            )
        elif choice == "6":
            run_auto_edit_only_flow(defaults, error_messages)
        elif choice == "7":
            run_caption_auto_edit_only_flow(defaults, error_messages)
        elif choice == "8":
            run_funny_caption_auto_edit_only_flow(defaults, error_messages)
        elif choice == "9":
            run_caption_audit_only_flow(defaults, error_messages)
        elif choice == "10":
            print("Done.")
            break
        else:
            print("Invalid option. Choose 1-10.")


if __name__ == "__main__":
    main()
