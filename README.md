# Free daily YouTube Shorts automation

This repository is the starter pipeline for **somewhereelse**. It runs on GitHub Actions, selects a current Google Trends topic, uses the free Gemini API tier to write a short script based only on a Google News RSS summary, finds reusable images on Wikimedia Commons, creates narration with the open-source espeak-ng voice, renders a vertical 1080×1920 video with FFmpeg, and uploads it to YouTube.

## Cost

- GitHub Actions: standard runners are free for public repositories.
- Gemini API: the free tier has limited model access and rate limits; Google may change availability.
- Wikimedia Commons API: no API key required. Image credits are added to the description when metadata is available.
- FFmpeg and espeak-ng: free/open-source.
- YouTube Data API: standard quota includes video uploads; Google OAuth authorization is required.

No paid credits or subscriptions are used by this workflow.

## One-time setup still required

GitHub cannot publish to your YouTube channel until you authorize it. Add these four values under **Repository → Settings → Secrets and variables → Actions → New repository secret**:

1. `GEMINI_API_KEY` — a free key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2. `YOUTUBE_CLIENT_ID`
3. `YOUTUBE_CLIENT_SECRET`
4. `YOUTUBE_REFRESH_TOKEN`

The three YouTube values come from a Google Cloud OAuth client configured for the YouTube Data API v3 with the `youtube.upload` scope. Keep them in GitHub Secrets only; never commit them or paste them into chat.

## Run

After the four secrets are added, open **Actions → Daily YouTube Short → Run workflow**. The workflow is also scheduled daily at 16:00 Korea time (07:00 UTC).

The first run should be checked for output quality and upload status. The pipeline currently creates a narrated image slideshow, not AI-generated cinematic footage. Topic selection and free-tier API availability can vary, and a failed run will save a short-lived diagnostic artifact when possible.

## Important

- The script uses source summaries and instructs the model not to invent facts; automated summaries can still be imperfect, so review early uploads.
- Images are sourced from Wikimedia Commons; attribution details are appended when available. Always check the relevant file license if you reuse an asset outside this workflow.
- YouTube uploads are public. Change `privacyStatus` in `shorts.py` to `unlisted` if you want to test privately first.
