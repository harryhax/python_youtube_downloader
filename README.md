# YouTube Video Downloader

A simple Python script that downloads a YouTube video, downloads its captions, and can optionally export a clipped segment.

It can also auto-edit the video by removing long no-talking sections and stitching the remaining speaking parts together.

## Requirements

- Python 3.10+
- `ffmpeg` (only required when using `--start` and `--end` clip options)

On macOS, you can install `ffmpeg` with Homebrew:

```bash
brew install ffmpeg
```

## Setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Optional: edit `config.json` to change defaults and user-facing error messages.

Example defaults in `config.json`:

```json
{
	"defaults": {
		"video_format": "bestvideo+bestaudio/best",
		"fallback_video_formats": ["best[ext=mp4]", "best"],
		"live_video_format": "best[ext=mp4]/best",
		"live_fallback_video_formats": ["best", "worst[ext=mp4]/worst"],
		"retries_per_format": 2,
		"auto_edit": false,
		"speech_padding_seconds": 2.5,
		"silence_threshold_db": -35,
		"min_silence_duration": 0.7,
		"min_speech_duration": 0.2,
		"auto_edit_max_input_minutes": null,
		"caption_auto_edit_audit": false
	}
}
```

## Usage

### Interactive menu (recommended)

Run the menu-driven interface:

```bash
python3 video_menu.py
```

Menu sections include:

- Download workflows: plain download, clip export, voice-based auto-edit, caption-based auto-edit
- Local file workflows: voice-based auto-edit, caption-based auto-edit, and caption timeline audit for existing downloaded files
- Exit

When using "Auto-edit an existing local video", you can optionally set a max input minutes value to test only the beginning of a long video.

The local auto-edit menu items now list available video and caption files from `downloads/` so you can pick by number instead of typing full paths.

Use menu option `7` for caption timeline audit only (stats, cuts, old vs new timeline) without rendering a new output video.

### Direct downloader CLI

Run the script with a YouTube URL:

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

For URLs with query params (for example `?feature=share`), pass them normally or wrap the full URL in quotes:

```bash
python3 download_youtube_video.py "https://youtube.com/live/zmC3JI1cf7k?feature=share"
```

Use a custom config file path if needed:

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --config my_config.json
```

By default, each video is saved in its own folder under `downloads/`, for example `downloads/My_Video_Title_VIDEO_ID/`.

The folder contains:

- The downloaded video (`.mp4`)
- Caption files (when available, including auto-generated captions) in `.vtt` format

By default, the script requests only `en` and `en-orig` captions to reduce rate limiting.

### Choose caption languages

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --caption-langs en,es
```

### Request all caption languages

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --all-captions
```

### Save to a custom folder

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --output-dir my_videos
```

### Download a clip between two timestamps

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --start 00:00:10 --end 00:00:25
```

### Auto-edit to remove no-talking sections

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --auto-edit
```

### Caption-based auto-edit using subtitle timing

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --caption-based-auto-edit
```

Enable timeline audit output (old vs new, cuts, kept/removed time):

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --caption-based-auto-edit --caption-auto-edit-audit
```

This mode uses downloaded caption cue timing instead of silence detection, which can be faster and easier to compare against the voice-based version.

Performance note: if `max input minutes` is left as `none`, the editor processes the full source timeline, which can still take a while on long videos.

### Auto-edit with custom padding around cuts

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --auto-edit --speech-padding-seconds 3
```

### Separate auto-edit script for local files

```bash
python3 auto_edit_video.py path/to/video.mp4
```

Only process the first N minutes (useful for testing):

```bash
python3 auto_edit_video.py path/to/video.mp4 --max-input-minutes 5
```

With custom parameters:

```bash
python3 auto_edit_video.py path/to/video.mp4 --speech-padding-seconds 3 --silence-threshold-db -32 --min-silence-duration 0.9 --min-speech-duration 0.3
```

### Tune talking/silence detection

```bash
python3 download_youtube_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --auto-edit --silence-threshold-db -32 --min-silence-duration 0.9 --min-speech-duration 0.3
```

Supported time formats:

- `SS`
- `MM:SS`
- `HH:MM:SS`

## Notes

- The script expects a valid YouTube URL containing a video ID.
- If clipping is requested, `ffmpeg` must be installed and available on your `PATH`.
- Captions availability depends on what YouTube provides for the selected video.
- Video and captions are downloaded independently. If captions fail (rate limit, unavailable language, etc.), the video download still succeeds.
- Errors are shown in a user-friendly format by default. You can customize the text in `config.json`.
- Video downloads automatically retry and fall back through `fallback_video_formats` when stream requests fail (for example HTTP 403/429).
- Live URLs automatically use `live_video_format` and `live_fallback_video_formats` before giving up.
- Auto-edit uses `ffmpeg` silence detection to keep talking regions, then concatenates those segments into a new file with configurable padding around each cut.
- Caption-based auto-edit uses downloaded `.vtt` cue timing to keep captioned regions, then trims and concatenates those segments into a separate comparison output.
- Caption-based workflows can print an audit report showing original caption timeline vs new kept timeline plus cut counts and kept/removed duration.
