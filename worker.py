#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import re
import time
import glob
import logging
import requests

import pysubs2

# Arguments
job_id = sys.argv[1]
src = sys.argv[2]
target = sys.argv[3]
is_url = bool(int(sys.argv[4]))
font_size = sys.argv[5]

APP_DIR = os.path.dirname(__file__)
JOB_DIR = os.path.join(APP_DIR, "output", job_id)
STATUS = os.path.join(JOB_DIR, "status.json")
LOG_FILE = os.path.join(JOB_DIR, "worker.log")
os.makedirs(JOB_DIR, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# Get Cookies from Secret
def get_cookies_path():
    secret_cookies = os.getenv("COOKIES_TXT")
    logging.info(f"DEBUG: COOKIES_TXT env: {'EXISTS' if secret_cookies else 'MISSING'} | Length: {len(secret_cookies) if secret_cookies else 0}")
    
    if secret_cookies and len(secret_cookies.strip()) > 50:
        path = os.path.join(JOB_DIR, "cookies_from_secret.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(secret_cookies.strip())
        logging.info("SUCCESS: Cookies loaded from Secret!")
        return path

    local_path = os.path.join(APP_DIR, "cookies.txt")
    if os.path.exists(local_path):
        logging.info("SUCCESS: Cookies from local file")
        return local_path

    logging.error("CRITICAL: NO COOKIES! Eporner akan gagal (age gate)")
    return None

COOKIES_PATH = get_cookies_path()

# Helper
def update(status, log_msg=""):
    data = {"status": status, "log": log_msg}
    if status == "done":
        data["output"] = f"/api/output/{job_id}"
    try:
        with open(STATUS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to write status: {e}")

def run(cmd):
    logging.info("RUN → " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    p = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        capture_output=True,
        text=True,
        cwd=APP_DIR,
    )
    if p.stdout:
        logging.info(p.stdout[-2000:])
    if p.stderr:
        logging.error(p.stderr[-2000:])
    return p.returncode

def find_downloaded_video(job_dir):
    for pattern in [os.path.join(job_dir, "video.*"), os.path.join(job_dir, "*.*")]:
        for f in glob.glob(pattern):
            if any(x in f for x in [".part", ".temp", ".ytdl", ".frag"]):
                continue
            try:
                if os.path.getsize(f) > 300_000:
                    return f
            except: pass
    return None

# EPORNER MANUAL SCRAPE JSON-LD + COOKIES (FIX 100% Des 2025)
def download_eporner_direct(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

    update("downloading", "Manual scrape Eporner JSON-LD with cookies...")
    try:
        headers = {"User-Agent": ua, "Referer": url}
        session = requests.Session()
        if COOKIES_PATH:
            with open(COOKIES_PATH, 'r') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        parts = line.strip().split('\t')
                        if len(parts) >= 7:
                            domain, _, path, secure, expires, name, value = parts[:7]
                            session.cookies.set(name, value, domain=domain, path=path)

        resp = session.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logging.error(f"Page load failed: {resp.status_code}")
            return None

        # Extract JSON-LD script
        json_match = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', resp.text, re.DOTALL | re.IGNORECASE)
        if not json_match:
            logging.error("No JSON-LD script found")
            return None

        data = json.loads(json_match.group(1))
        sources = []

        # Recursive extract contentUrl
        def extract_sources(obj):
            if isinstance(obj, dict):
                if obj.get("@type") == "VideoObject":
                    sources.extend(obj.get("contentUrl", []))
                for v in obj.values():
                    extract_sources(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract_sources(item)

        extract_sources(data)

        if not sources:
            logging.error("No MP4 sources in JSON")
            return None

        # Sort by quality (1080p > 720p > 480p)
        def get_quality(u):
            if "1080" in u: return 1080
            if "720" in u: return 720
            if "480" in u: return 480
            return 360
        sources.sort(key=get_quality, reverse=True)
        best_url = sources[0]
        logging.info(f"Best MP4: {best_url[:150]}... (quality: {get_quality(best_url)}p)")

        # Download with yt-dlp + cookies
        cmd = f'yt-dlp -o "{video_path}" "{best_url}" --user-agent "{ua}" --referer "{url}" --retries 10'
        if COOKIES_PATH:
            cmd += f' --cookies "{COOKIES_PATH}"'
        if run(cmd) == 0 and os.path.getsize(video_path) > 500_000:
            logging.info("EPORNER SUCCESS with JSON scrape!")
            return video_path

        # Fallback curl
        curl_cmd = f'curl -L -k --fail --retry 10 --max-time 900 -o "{video_path}" "{best_url}" -H "User-Agent: {ua}" -H "Referer: {url}"'
        if COOKIES_PATH:
            curl_cmd += f' --cookie-jar "{COOKIES_PATH}"'
        if run(curl_cmd) == 0 and os.path.getsize(video_path) > 500_000:
            logging.info("EPORNER SUCCESS with curl fallback!")
            return video_path

    except Exception as e:
        logging.error(f"Scrape error: {e}")
    return None

# Download Video Main
def download_video(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

    # Eporner → manual scrape
    if "eporner.com" in url.lower():
        return download_eporner_direct(url)

    # Other sites → yt-dlp with cookies
    base_cmd = f'yt-dlp -o "{video_path}" "{url}" --impersonate chrome --user-agent "{ua}" --referer "{url}" --retries 10 --fragment-retries 20 --no-check-certificate'
    if COOKIES_PATH:
        base_cmd += f' --cookies "{COOKIES_PATH}"'

    commands = [
        base_cmd + " --concurrent-fragments 8",
        base_cmd,
        base_cmd.replace("--impersonate chrome", ""),
        f'yt-dlp -o "{video_path}" "{url}" -f best' + (f' --cookies "{COOKIES_PATH}"' if COOKIES_PATH else ""),
    ]

    for i, cmd in enumerate(commands, 1):
        update("downloading", f"yt-dlp method {i}...")
        if run(cmd) == 0:
            file = find_downloaded_video(JOB_DIR)
            if file:
                if file != video_path:
                    os.rename(file, video_path)
                return video_path
        time.sleep(3)

    # Final curl fallback
    curl_cmd = f'curl -L -k --fail --retry 10 --max-time 900 -o "{video_path}" "{url}" -H "User-Agent: {ua}" -H "Referer: {url}"'
    if COOKIES_PATH:
        curl_cmd += f' --cookie-jar "{COOKIES_PATH}"'
    if run(curl_cmd) == 0 and os.path.getsize(video_path) > 300_000:
        return video_path

    return None

# Extract Audio
def extract_audio(video, out):
    cmd = f'{FFMPEG} -y -i "{video}" -vn -ac 1 -ar 16000 -acodec pcm_s16le "{out}" -loglevel error'
    return run(cmd) == 0

# Transcribe
def transcribe(audio_path, output_srt):
    update("transcribing", "Loading Whisper...")
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=5, vad_filter=True)
        with open(output_srt, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                s, e = seg.start, seg.end
                f.write(f"{i}\n{int(s//3600):02d}:{int(s%3600//60):02d}:{int(s%60):02d},{int(s*1000%1000):03d} --> ")
                f.write(f"{int(e//3600):02d}:{int(e%3600//60):02d}:{int(e%60):02d},{int(e*1000%1000):03d}\n{seg.text.strip()}\n\n")
        return True
    except Exception as e:
        logging.error(f"Whisper error: {e}")
        update("failed", "Transcription failed")
        return False

# Translate
def translate_srt(path, lang):
    subs = pysubs2.load(path)
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source='auto', target=lang)
        for i, line in enumerate(subs):
            if line.text.strip():
                line.text = tr.translate(line.text.strip())
                if i % 15 == 0:
                    update("translating", f"Translated {i} lines...")
    except Exception as e:
        logging.warning(f"Translation failed: {e}")
    out = os.path.join(JOB_DIR, "subs.srt")
    subs.save(out)
    return out

# Burn
def burn(video, srt, out, size):
    srt_escaped = srt.replace(":", "\\:")
    vf = f"subtitles='{srt_escaped}':force_style='FontSize={size},OutlineColour=&H80000000,BorderStyle=3,BackColour=&H80000000,Alignment=2'"
    cmd = [FFMPEG, "-y", "-i", video, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "copy", out]
    return run(cmd) == 0

# Main Flow
update("started", "Worker started")

final_url = src.strip() if is_url else src
if is_url and not final_url.startswith("http"):
    m = re.search(r'src=[\'"]([^\'"]+)', src)
    final_url = m.group(1) if m else src

update("downloading", "Starting download...")
video_file = download_video(final_url)
if not video_file:
    update("failed", "Download failed after all attempts")
    sys.exit(1)

audio = os.path.join(JOB_DIR, "audio.wav")
if not extract_audio(video_file, audio):
    update("failed", "Audio extraction failed")
    sys.exit(1)

raw_srt = os.path.join(JOB_DIR, "raw.srt")
if not transcribe(audio, raw_srt):
    sys.exit(1)

update("translating", "Translating...")
final_srt = translate_srt(raw_srt, target)

update("burning", "Burning subtitles...")
out_video = os.path.join(JOB_DIR, "output.mp4")
if burn(video_file, final_srt, out_video, font_size):
    update("done", "Success! Video ready")
else:
    update("failed", "Burn failed")