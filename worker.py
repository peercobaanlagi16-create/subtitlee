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
# COOKIES FROM SECRET
# ======================================
def get_cookies_path():
    secret = os.getenv("COOKIES_TXT")
    logging.info(f"DEBUG: COOKIES_TXT env: {'EXISTS' if secret else 'MISSING'} | Length: {len(secret) if secret else 0}")
    if secret and len(secret.strip()) > 50:
        path = os.path.join(JOB_DIR, "cookies_from_secret.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(secret.strip())
        logging.info("SUCCESS: Cookies loaded from Koyeb Secret!")
        return path
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
        logging.error(f"Status write error: {e}")

def run(cmd):
    logging.info("RUN → " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, cwd=APP_DIR)
    if p.stdout: logging.info(p.stdout[-1500:])
    if p.stderr: logging.error(p.stderr[-1500:])
    return p.returncode

def find_video(job_dir):
    for f in glob.glob(os.path.join(job_dir, "*.*")):
        if any(x in f for x in [".part", ".temp", ".ytdl", ".frag"]): continue
        if os.path.getsize(f) > 500_000:
            return f
    return None

# ======================================
# EPORNER MANUAL SCRAPER (100% Jalan Des 2025)
# ======================================
def download_eporner(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    headers = {"User-Agent": ua, "Referer": url, "Accept": "*/*", "Origin": "https://www.eporner.com"}

    update("downloading", "Eporner: Manual scrape with cookies...")
    try:
        session = requests.Session()
        if COOKIES_PATH:
            with open(COOKIES_PATH) as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        parts = line.strip().split('\t')
                        if len(parts) >= 7:
                            name, value = parts[-2], parts[-1]
                            session.cookies.set(name, value, domain=parts[0])

        resp = session.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logging.error("Failed to load page")
            return None

        # 1. Coba JSON-LD
        sources = []
        json_ld = re.search(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', resp.text, re.DOTALL | re.IGNORECASE)
        if json_ld:
            try:
                data = json.loads(json_ld.group(1))
                def extract(obj):
                    if isinstance(obj, dict):
                        if obj.get("@type") == "VideoObject":
                            sources.extend(obj.get("contentUrl", []))
                        for v in obj.values():
                            extract(v)
                    elif isinstance(obj, list):
                        for i in obj:
                            extract(i)
                extract(data)
            except: pass

        # 2. Fallback: cari <source src="...">
        if not sources:
            sources = re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', resp.text)
            sources = [s for s in sources if "mp4" in s.lower()]

        # 3. Fallback: cari data-video-url
        if not sources:
            match = re.search(r'data-video-url=["\']([^"\']+)["\']', resp.text)
            if match:
                sources = [match.group(1)]

        if not sources:
            logging.error("No video source found")
            return None

        # Pilih terbaik
        def quality(u):
            return 1080 if "1080" in u else 720 if "720" in u else 480 if "480" in u else 360
        sources.sort(key=quality, reverse=True)
        best_url = sources[0]
        logging.info(f"Best MP4 found: {best_url[:120]}...")

        # Download
        cmd = f'yt-dlp -o "{video_path}" "{best_url}" --user-agent "{ua}" --referer "{url}" --retries 10'
        if COOKIES_PATH:
            cmd += f' --cookies "{COOKIES_PATH}"'
        if run(cmd) == 0 and os.path.getsize(video_path) > 500_000:
            logging.info("EPORNER SUCCESS!")
            return video_path

        # Curl fallback
        curl_cmd = f'curl -L -k --fail --retry 10 --max-time 900 -o "{video_path}" "{best_url}" -H "User-Agent: {ua}" -H "Referer: {url}"'
        if COOKIES_PATH:
            curl_cmd += f' --cookie-jar "{COOKIES_PATH}"'
        if run(curl_cmd) == 0 and os.path.getsize(video_path) > 500_000:
            logging.info("EPORNER SUCCESS via curl!")
            return video_path

    except Exception as e:
        logging.error(f"Eporner scrape error: {e}")
    return None

# ======================================
# DOWNLOAD UTAMA
# ======================================
def download_video(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

    if "eporner.com" in url.lower():
        result = download_eporner(url)
        if result:
            return result

    # Lainnya pakai yt-dlp + cookies
    base = f'yt-dlp -o "{video_path}" "{url}" --user-agent "{ua}" --referer "{url}" --retries 10'
    if COOKIES_PATH:
        base += f' --cookies "{COOKIES_PATH}"'

    commands = [
        base + " --impersonate chrome --concurrent-fragments 8",
        base + " --impersonate chrome",
        base,
        f'yt-dlp -o "{video_path}" "{url}" -f best' + (f' --cookies "{COOKIES_PATH}"' if COOKIES_PATH else ""),
    ]

    for i, cmd in enumerate(commands, 1):
        update("downloading", f"Method {i}/4...")
        if run(cmd) == 0:
            f = find_video(JOB_DIR)
            if f:
                if f != video_path:
                    os.rename(f, video_path)
                return video_path
        time.sleep(3)

    return None

# ======================================
# Extract, Transcribe, Translate, Burn (sama seperti sebelumnya)
# ======================================
def extract_audio(v, o):
    return run(f'{FFMPEG} -y -i "{v}" -vn -ac 1 -ar 16000 -acodec pcm_s16le "{o}" -loglevel error') == 0

def transcribe(a, srt):
    update("transcribing", "Whisper running...")
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(a, beam_size=5, vad_filter=True)
        with open(srt, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segs, 1):
                s, e = seg.start, seg.end
                f.write(f"{i}\n{int(s//3600):02d}:{int(s%3600//60):02d}:{int(s%60):02d},{int(s*1000%1000):03d} --> ")
                f.write(f"{int(e//3600):02d}:{int(e%3600//60):02d}:{int(e%60):02d},{int(e*1000%1000):03d}\n{seg.text.strip()}\n\n")
        return True
    except Exception as e:
        logging.error(f"Whisper failed: {e}")
        return False

def translate_srt(p, lang):
    subs = pysubs2.load(p)
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source='auto', target=lang)
        for line in subs:
            if line.text.strip():
                line.text = tr.translate(line.text.strip())
    except: pass
    out = os.path.join(JOB_DIR, "subs.srt")
    subs.save(out)
    return out

def burn(v, s, o, size):
    s_esc = s.replace(":", "\\:")
    vf = f"subtitles='{s_esc}':force_style='FontSize={size},OutlineColour=&H80000000,BorderStyle=3,BackColour=&H80000000,Alignment=2'"
    return run([FFMPEG, "-y", "-i", v, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "copy", o]) == 0

# ======================================
# MAIN
# ======================================
update("started", "Worker start")

final_url = src.strip() if is_url else src
if is_url and not final_url.startswith("http"):
    m = re.search(r'src=[\'"]([^\'"]+)', src)
    final_url = m.group(1) if m else src

update("downloading", "Downloading...")
video = download_video(final_url)
if not video:
    update("failed", "Download failed")
    sys.exit(1)

audio = os.path.join(JOB_DIR, "audio.wav")
if not extract_audio(video, audio):
    update("failed", "Audio failed")
    sys.exit(1)

raw_srt = os.path.join(JOB_DIR, "raw.srt")
if not transcribe(audio, raw_srt):
    sys.exit(1)

update("translating", "Translating...")
final_srt = translate_srt(raw_srt, target)

update("burning", "Burning subtitles...")
out = os.path.join(JOB_DIR, "output.mp4")
if burn(video, final_srt, out, font_size):
    update("done", "Done! Video ready")
else:
    update("failed", "Burn failed")