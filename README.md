# ReelDissect

Share any Instagram Reel, TikTok, YouTube Short (or any video link) to ReelDissect and get instant AI-powered notes: key points, research queries, and people/concepts mentioned.

---

## How it works

1. You hit **Share** on a reel → choose **ReelDissect** from the Android share sheet
2. The app downloads the video, extracts audio, and transcribes it with Whisper
3. NVIDIA NIM (Llama 3) reads the transcript and returns structured notes
4. Notes are saved locally on your phone for later

---

## Deploy to Render (5 min)

### 1. Push to GitHub

```bash
cd ReelDissect
git init
git add .
git commit -m "initial"
gh repo create reeldissect --public --push
```

### 2. Create a Render Web Service

- Go to https://render.com → **New → Web Service**
- Connect your GitHub repo
- Render will detect `render.yaml` automatically
- Set **Build from** → Docker

### 3. Add your NVIDIA NIM API key

In the Render dashboard → your service → **Environment**:

| Key | Value |
|-----|-------|
| `NVIDIA_NIM_API_KEY` | your key from https://build.nvidia.com |
| `NIM_MODEL` | `meta/llama-3.1-8b-instruct` *(default)* |

> **Tip:** For better analysis quality, try `meta/llama-3.3-70b-instruct`.

### 4. Wait for deploy

First deploy takes ~5 min (downloads Whisper model during Docker build).
Your app will be live at `https://reeldissect.onrender.com` (or similar).

---

## Install on Android

1. Open **Chrome** on your Android phone
2. Go to your Render URL
3. Tap the **⋮ menu → Add to Home screen**
4. Now open any reel → tap **Share** → you'll see **ReelDissect** in the list

> **Note:** The share target only appears after you add the app to your home screen.

---

## Use it

**Via share sheet (recommended):**
1. Open a reel in Instagram / TikTok / YouTube
2. Tap **Share**
3. Select **ReelDissect**
4. Wait ~20–60 sec while it downloads + transcribes + analyzes
5. Read your notes, tap search queries to open Google

**Via URL paste:**
- Open the app manually and paste any video URL into the input bar

---

## Notes on platform support

| Platform | Works? | Notes |
|----------|--------|-------|
| Instagram Reels | ✅ | Public reels only |
| TikTok | ✅ | Public videos |
| YouTube Shorts | ✅ | |
| YouTube (full) | ✅ | |
| Twitter/X | ✅ | Public videos |
| Facebook | ⚠️ | May require login |
| Private content | ❌ | Not supported |

---

## Render free tier caveats

- Sleeps after **15 min** of inactivity — first request after sleep takes ~30s to wake
- **512 MB RAM** — sufficient for the `small` Whisper model
- Upgrade to **Starter** plan ($7/mo) for always-on + more RAM

---

## Local development

```bash
pip install -r requirements.txt
# also: brew install ffmpeg (Mac) or apt install ffmpeg (Linux)

export NVIDIA_NIM_API_KEY=your_key_here
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

---

## Project structure

```
ReelDissect/
├── main.py             # FastAPI backend — download, transcribe, analyze
├── requirements.txt
├── Dockerfile          # ffmpeg + whisper pre-baked
├── render.yaml         # one-click Render deploy
├── static/
│   ├── index.html      # Android PWA — all UI, no framework
│   ├── manifest.json   # Web App Manifest + share_target
│   ├── sw.js           # Service Worker (offline cache)
│   ├── icon-192.svg
│   └── icon-512.svg
└── README.md
```
