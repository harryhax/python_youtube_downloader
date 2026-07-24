# YouTube Video Downloader

A simple Python script that downloads a YouTube video, downloads its captions, and can optionally export a clipped segment.

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
		"retries_per_format": 2
	}
}
```

## Usage

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
