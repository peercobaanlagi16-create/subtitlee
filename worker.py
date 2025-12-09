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

# ======================================
# Arguments
# ======================================
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

# ======================================
# Logging
# ======================================
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

# ======================================
# GET COOKIES (dari Secret atau file lokal)
# ======================================
def get_cookies_path():
    secret_cookies = os.getenv("COOKIES_TXT")  # ← nama secret di Koyeb
    if secret_cookies:
        path = os.path.join(JOB_DIR, "cookies_from_secret.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(secret_cookies.strip() + "\n")
            logging.info("Cookies loaded from Koyeb Secret")
            return path
        except Exception as e:
            logging.error(f"Failed to write secret cookies: {e}")

    local_path = os.path.join(APP_DIR, "cookies.txt")
    if os.path.exists(local_path):
        logging.info("Cookies loaded from local cookies.txt")
        return local_path

    logging.warning("No cookies found! Age-gated sites may fail")
    return None

COOKIES_PATH = get_cookies_path()

# ======================================
# Helper
# ======================================
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

# ======================================
# EPORNER DIRECT MP4 SCRAPER (2025) – WITH COOKIES
# ======================================
def download_eporner_direct(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

    update("downloading", "Scraping Eporner MP4 sources...")
    try:
        headers = {"User-Agent": ua, "Referer": url}
        session = requests.Session()
        if COOKIES_PATH:
            # Load Netscape format cookies
            with open(COOKIES_PATH) as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        parts = line.strip().split('\t')
                        if len(parts) >= 7:
                            name, value = parts[-2], parts[-1]
                            session.cookies.set(name, value, domain=parts[0])

        resp = session.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None

        # Cari JSON-LD
        json_match = re.search(r'<script type=["\']application/ld\+json["\']>(.*?)</script>', resp.text, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group(1))
        sources = []

        def extract_urls(obj):
            if isinstance(obj, dict):
                if obj.get("@type") == "VideoObject":
                    sources.extend(obj.get("contentUrl", []))
                for v in obj.values():
                    extract_urls(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract_urls(item)

        extract_urls(data)

        if not sources:
            return None

        # Pilih kualitas tertinggi
        sources.sort(key=lambda x: int(re.search(r'(\d+)p', x) or re.search(r'/(\d+)/', x) or [0])[0] or 0, reverse=True)
        best_url = sources[0]
        logging.info(f"Best quality: {best_url[:120]}...")

        # Download dengan yt-dlp + cookies
        cmd = f'yt-dlp -o "{video_path}" "{best_url}" --user-agent "{ua}" --referer "{url}" --retries 10'
        if COOKIES_PATH:
            cmd += f' --cookies "{COOKIES_PATH}"'

        if run(cmd) == 0 and os.path.getsize(video_path) > 500_000:
            return video_path

    except Exception as e:
        logging.error(f"Eporner scraper error: {e}")
    return None

# ======================================
# DOWNLOAD UTAMA
# ======================================
def download_video(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

    # Eporner → scraper khusus
    if "eporner.com" in url.lower():
        result = download_eporner_direct(url)
        if result:
            return result

    # Situs lain → yt-dlp normal + cookies kalau ada
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
        update("downloading", f"Method {i}/4 – yt-dlp")
        if run(cmd) == 0:
            file = find_downloaded_video(JOB_DIR)
            if file:
                if file != video_path:
                    os.rename(file, video_path)
                return video_path
        time.sleep(3)

    return None

# ======================================
# Extract, Transcribe, Translate, Burn (sama)
# ======================================
def extract_audio(video, out):
    cmd = f'{FFMPEG} -y -i "{video}" -vn -ac 1 -ar 16000 -acodec pcm_s16le "{out}" -loglevel error'
    return run(cmd) == 0

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

def translate_srt(path, lang):
    subs = pysubs2.load(path)
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source='auto', target=lang)
        for i, line in enumerate(subs):
            if line.text.strip():
                line.text = tr.translate(line.text.strip())
    except: pass
    out = os.path.join(JOB_DIR, "subs.srt")
    subs.save(out)
    return out

def burn(video, srt, out, size):
    srt_escaped = srt.replace(":", "\\:")
    vf = f"subtitles='{srt_escaped}':force_style='FontSize={size},OutlineColour=&H80000000,BorderStyle=3,BackColour=&H80000000,Alignment=2'"
    cmd = [FFMPEG, "-y", "-i", video, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "copy", out]
    return run(cmd) == 0

# ======================================
# MAIN
# ======================================
update("started", "Worker started")

final_url = src.strip() if is_url else src
if is_url and not final_url.startswith("http"):
    m = re.search(r'src=[\'"]([^\'"]+)', src)
    final_url = m.group(1) if m else src

update("downloading", "Downloading video...")
video_file = download_video(final_url)
if not video_file:
    update("failed", "Download failed")
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