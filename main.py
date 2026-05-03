import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel
from openai import OpenAI
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="ReelDissect API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# NVIDIA NIM client  (OpenAI-compatible)
# ---------------------------------------------------------------------------

NIM_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
NIM_MODEL   = os.getenv("NIM_MODEL", "meta/llama-3.1-8b-instruct")

nim_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NIM_API_KEY,
)

# ---------------------------------------------------------------------------
# Whisper model  (loaded once at startup — ~244 MB, CPU-friendly)
# ---------------------------------------------------------------------------

print("⏳ Loading Whisper model …")
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
print("✅ Whisper model ready")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"https?://[^\s]+")


def _extract_url(raw: str) -> str:
    """Pull the first HTTP URL out of a blob of text (Android share text often includes extra copy)."""
    raw = raw.strip()
    if raw.startswith("http"):
        return raw
    m = URL_RE.search(raw)
    return m.group(0) if m else raw


def _download_audio(video_url: str, out_stem: str) -> tuple[str, str, int]:
    """
    Download best audio track and convert to MP3 via yt-dlp + ffmpeg.
    Returns (mp3_path, video_title, duration_seconds).
    """
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_stem + ".%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "96",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        # Some platforms need a browser-like UA
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Mobile Safari/537.36"
            )
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        title    = info.get("title", "Unknown video")
        duration = info.get("duration", 0) or 0

    mp3_path = out_stem + ".mp3"
    if not Path(mp3_path).exists():
        # yt-dlp may have kept a different extension — find it
        candidates = list(Path(out_stem).parent.glob(Path(out_stem).name + ".*"))
        if not candidates:
            raise FileNotFoundError("Audio file not found after download")
        mp3_path = str(candidates[0])

    return mp3_path, title, duration


def _transcribe(audio_path: str) -> str:
    """Return plain-text transcript using faster-whisper (auto language detection)."""
    segments, _ = whisper_model.transcribe(
        audio_path,
        beam_size=5,
        language=None,   # auto-detect
        vad_filter=True, # skip silence
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


def _analyze(transcript: str, video_title: str, url: str) -> dict:
    """Send transcript to NVIDIA NIM and return structured analysis as a dict."""

    system_prompt = (
        "You are a precise content analyst. Your job is to extract structured "
        "knowledge from video transcripts so the viewer can research topics later. "
        "Always respond with valid JSON only — no markdown, no extra text."
    )

    user_prompt = f"""Analyze this video transcript and return a JSON object with EXACTLY this structure:

{{
  "title": "Short descriptive title of what the video is about (max 10 words)",
  "summary": "2-3 sentence plain-language summary of the video's main argument or content",
  "key_points": [
    "First key point, claim, or fact the video makes",
    "Second key point",
    "Third key point"
  ],
  "research_queries": [
    "exact Google search string to learn more about the main topic",
    "search string for a specific claim or concept mentioned",
    "search string for related academic or journalistic sources"
  ],
  "mentioned": {{
    "people": ["Full Name (role/context)"],
    "sources": ["book title / article / study / documentary mentioned"],
    "concepts": ["key term or concept the video discusses"]
  }},
  "tags": ["topic1", "topic2", "topic3"]
}}

Rules:
- key_points: 3–5 items, each a complete sentence
- research_queries: 3–5 items, write them like you'd type into Google
- mentioned lists: only include items actually named in the transcript; use [] if none
- tags: 2–5 short lowercase topic tags
- If the transcript is empty or unclear, use the video title to make best-effort guesses

Video title: {video_title}
Video URL: {url}

Transcript:
\"\"\"
{transcript[:5000]}
\"\"\"
"""

    response = nim_client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model wrapped its JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    url: str


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    url = _extract_url(req.url)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Could not find a valid URL in the shared text.")

    loop = asyncio.get_event_loop()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_stem = os.path.join(tmpdir, "audio")

        # 1. Download
        try:
            audio_path, video_title, duration = await loop.run_in_executor(
                None, _download_audio, url, out_stem
            )
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Could not download video. It may be private or geo-restricted. ({e})",
            )

        # 2. Transcribe
        try:
            transcript = await loop.run_in_executor(None, _transcribe, audio_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

        # 3. Analyze
        try:
            analysis = await loop.run_in_executor(
                None, _analyze, transcript, video_title, url
            )
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="AI returned invalid JSON — try again.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI analysis failed: {e}")

        analysis["url"]                = url
        analysis["duration_seconds"]   = duration
        analysis["transcript_preview"] = (transcript[:400] + "…") if len(transcript) > 400 else transcript
        analysis["has_transcript"]     = bool(transcript)

        return analysis


@app.get("/api/health")
def health():
    return {"status": "ok", "model": NIM_MODEL, "whisper": "small"}


# ---------------------------------------------------------------------------
# PWA routes  (must come BEFORE the static mount)
# ---------------------------------------------------------------------------

@app.get("/share-target")
async def share_target():
    """Android share-sheet lands here; serve the SPA which handles the URL params."""
    return FileResponse("static/index.html")


# Serve static PWA files at root (catches everything else)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
