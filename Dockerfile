# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── System deps: ffmpeg (required by yt-dlp audio extraction) ─────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ───────────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Pre-download Whisper "small" model so the first request isn't slow ─────────
RUN python -c "\
from faster_whisper import WhisperModel; \
WhisperModel('small', device='cpu', compute_type='int8'); \
print('Whisper model cached ✓')"

# ── App source ────────────────────────────────────────────────────────────────
COPY . .

# ── Run ───────────────────────────────────────────────────────────────────────
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
