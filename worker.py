#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import re
import time
import glob
import logging
import requests  # ← TAMBAH INI untuk manual scrape

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

# ======================================
# FFmpeg
# ======================================
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# ======================================
# Helper Functions
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
        logging.info(p.stdout[-3000:])
    if p.stderr:
        logging.error(p.stderr[-3000:])
    return p.returncode

def extract_src(embed):
    m = re.search(r'src=[\'"]([^\'"]+)', embed)
    return m.group(1) if m else embed

def find_downloaded_video(job_dir):
    patterns = [
        os.path.join(job_dir, "video.*"),
        os.path.join(job_dir, "*.*")
    ]
    for pattern in patterns:
        for f in glob.glob(pattern):
            if any(ext in f for ext in [".part", ".temp", ".ytdl", ".frag"]):
                continue
            try:
                if os.path.getsize(f) > 200_000:  # >200KB
                    return f
            except: pass
    return None

# ======================================
# MANUAL EPORNER HASH EXTRACTION (FIX BROKEN EXTRACTOR)
# ======================================
def manual_eporner_download(url, video_path, ua):
    update("downloading", "Manual fallback: Extracting Eporner hash from webpage...")
    try:
        headers = {"User-Agent": ua, "Referer": url}
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logging.error(f"Failed to fetch webpage: {resp.status_code}")
            return None
        webpage = resp.text

        # Regex patterns dari yt-dlp source (multiple untuk 2025 structure)
        patterns = [
            r'hash\s*[:=]\s*["\']([a-f0-9]{32})["\']',  # Original hash
            r'"hash"\s*:\s*"([a-f0-9]{32})"',           # JSON hash
            r'videoHash["\']?\s*:\s*["\']?([a-f0-9]{32})["\']?',  # Video hash var
            r'id["\']?\s*:\s*["\']?([a-f0-9]{32})["\']?',          # ID fallback
            r'([a-f0-9]{32})\s*["\']?video["\']?',      # Reverse match
        ]
        hash_match = None
        for pat in patterns:
            match = re.search(pat, webpage, re.I)
            if match:
                hash_match = match.group(1)
                logging.info(f"Manual hash extracted: {hash_match}")
                break

        if not hash_match:
            logging.error("No hash found in webpage")
            return None

        # Build direct download URL untuk Eporner (free 720p)
        direct_url = f"https://www.eporner.com/video-{hash_match}/"
        logging.info(f"Direct URL built: {direct_url}")

        # Download pakai yt-dlp (atau curl kalau gagal)
        cmd = f'yt-dlp -o "{video_path}" "{direct_url}" --user-agent "{ua}" --referer "{url}" --retries 5 --no-check-certificate'
        rc = run(cmd)
        file = find_downloaded_video(JOB_DIR)
        if file:
            logging.info("SUCCESS with manual Eporner download!")
            return file

        # Fallback curl ke direct URL
        curl_cmd = f'curl -L -k --fail --retry 5 --max-time 600 -o "{video_path}" "{direct_url}" -H "User-Agent: {ua}" -H "Referer: {url}"'
        if run(curl_cmd) == 0 and os.path.getsize(video_path) > 200_000:
            logging.info("SUCCESS with curl fallback!")
            return video_path

    except Exception as e:
        logging.error(f"Manual Eporner extraction failed: {e}")
    return None

# ======================================
# DOWNLOAD VIDEO – Dengan Manual Fallback untuk Eporner
# ======================================
def download_video(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

    # DETECT EPORNER & GUNAKAN MANUAL FALLBACK PERTAMA
    if "eporner.com" in url:
        manual_file = manual_eporner_download(url, video_path, ua)
        if manual_file:
            return manual_file

    # Kalau bukan Eporner, lanjut ke yt-dlp methods
    commands = [
        # 1. Impersonate + full flags
        f'yt-dlp -o "{video_path}" "{url}" --impersonate chrome --user-agent "{ua}" --referer "{url}" --retries 5 --fragment-retries 15 --no-check-certificate --concurrent-fragments 8',

        # 2. Basic impersonate
        f'yt-dlp -o "{video_path}" "{url}" --impersonate chrome --user-agent "{ua}" --referer "{url}" --retries 5',

        # 3. Best format
        f'yt-dlp -o "{video_path}" "{url}" -f best --impersonate chrome --user-agent "{ua}" --referer "{url}"',

        # 4. Headers manual
        f'yt-dlp -o "{video_path}" "{url}" --impersonate chrome --add-header "Referer:{url}" --add-header "User-Agent:{ua}"',

        # 5. Quiet
        f'yt-dlp -o "{video_path}" "{url}" -q --no-warnings --impersonate chrome --user-agent "{ua}" --referer "{url}"',
    ]

    for i, cmd_str in enumerate(commands, 1):
        update("downloading", f"Attempt {i}/{len(commands)} – yt-dlp method...")
        logging.info(f"Trying yt-dlp method {i}...")
        rc = run(cmd_str)

        file = find_downloaded_video(JOB_DIR)
        if file:
            logging.info(f"SUCCESS with yt-dlp! Video: {file}")
            if file != video_path:
                os.rename(file, video_path)
            return video_path
        time.sleep(3)

    # Curl fallback (untuk direct MP4 links)
    update("downloading", "Final fallback: curl direct...")
    curl_cmd = f'curl -L -k --fail --retry 5 --max-time 600 -o "{video_path}" "{url}" -H "User-Agent: {ua}" -H "Referer: {url}"'
    if run(curl_cmd) == 0 and os.path.getsize(video_path) > 200_000:
        return video_path

    return None

# ======================================
# Extract Audio
# ======================================
def extract_audio(video, out):
    cmd = f'{FFMPEG} -y -i "{video}" -vn -ac 1 -ar 16000 -acodec pcm_s16le "{out}" -loglevel error'
    return run(cmd) == 0

# ======================================
# Transcribe (faster-whisper lazy import)
# ======================================
def transcribe(audio_path, output_srt):
    update("transcribing", "Loading Whisper model (small)...")
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        logging.error("faster_whisper import failed: " + str(e))
        update("failed", "faster_whisper not available")
        return False

    try:
        model = WhisperModel("small", device="cpu", compute_type="int8")
    except Exception as e:
        logging.error("Model load failed: " + str(e))
        update("failed", "Whisper model failed to load")
        return False

    update("transcribing", "Transcribing audio...")
    try:
        segments, _ = model.transcribe(audio_path, beam_size=5, vad_filter=True)
    except Exception as e:
        logging.error("Transcription error: " + str(e))
        update("failed", "Transcription failed")
        return False

    with open(output_srt, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = seg.start
            end = seg.end
            text = seg.text.strip()
            f.write(f"{i}\n")
            f.write(f"{int(start//3600):02d}:{int(start%3600//60):02d}:{int(start%60):02d},{int(start*1000%1000):03d} --> ")
            f.write(f"{int(end//3600):02d}:{int(end%3600//60):02d}:{int(end%60):02d},{int(end*1000%1000):03d}\n")
            f.write(text + "\n\n")
    return True

# ======================================
# Translate SRT
# ======================================
def translate_srt(path, target_lang):
    subs = pysubs2.load(path)
    count = 0
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target=target_lang)
        for line in subs:
            if line.text.strip():
                try:
                    line.text = translator.translate(line.text.strip())
                    count += 1
                    if count % 15 == 0:
                        update("translating", f"Translated {count} lines...")
                except:
                    pass
    except Exception as e:
        logging.warning("Translation failed, keeping original: " + str(e))

    out_path = os.path.join(JOB_DIR, "subs.srt")
    subs.save(out_path)
    return out_path

# ======================================
# Burn Subtitle
# ======================================
def escape(path):
    return path.replace("\\", "/").replace(":", "\\:")

def burn(video, srt, out, size):
    vf = f"subtitles='{escape(srt)}':force_style='FontSize={size},OutlineColour=&H80000000,BorderStyle=3,BackColour=&H80000000,Alignment=2'"
    cmd = [
        FFMPEG, "-y", "-i", video,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "copy",
        out
    ]
    return run(cmd) == 0

# ======================================
# MAIN FLOW
# ======================================
update("started", "Worker started")

# Determine final URL
if is_url:
    raw_url = src.strip()
    final_url = raw_url if raw_url.startswith("http") else extract_src(raw_url)
else:
    final_url = src

# Download
if is_url:
    update("downloading", "Starting video download...")
    video_file = download_video(final_url)
    if not video_file:
        update("failed", "Failed to download video after all attempts")
        sys.exit(1)
else:
    video_file = src

# Extract audio
audio_file = os.path.join(JOB_DIR, "audio.wav")
if not extract_audio(video_file, audio_file):
    update("failed", "Audio extraction failed")
    sys.exit(1)

# Transcribe
raw_srt = os.path.join(JOB_DIR, "raw.srt")
if not transcribe(audio_file, raw_srt):
    sys.exit(1)

# Translate
update("translating", "Translating subtitles...")
final_srt = translate_srt(raw_srt, target)

# Burn
update("burning", "Burning subtitles into video...")
output_video = os.path.join(JOB_DIR, "output.mp4")
if burn(video_file, final_srt, output_video, font_size):
    update("done", "Video with subtitles ready!")
else:
    update("failed", "Failed to burn subtitles")
    sys.exit(1)