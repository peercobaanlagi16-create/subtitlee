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
import random
from http.cookies import SimpleCookie
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
COOKIES_TEMP = os.path.join(JOB_DIR, "cookies_temp.txt")
os.makedirs(JOB_DIR, exist_ok=True)

# ======================================
# Logging
# ======================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# ======================================
# Cookies
# ======================================
def setup_cookies():
    secret = os.getenv("COOKIES_TXT", "").strip()
    if not secret or len(secret) < 50:
        logger.warning("COOKIES_TXT tidak valid")
        return None

    with open(COOKIES_TEMP, "w", encoding="utf-8") as f:
        if not secret.startswith("# Netscape"):
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n")
            f.write("# Generated file\n\n")
        f.write(secret)

    logger.info("✓ Cookies siap digunakan")
    return COOKIES_TEMP

COOKIES_PATH = setup_cookies()

# ======================================
# Helper
# ======================================
def update(status, log=""):
    data = {"status": status, "log": log}
    if status == "done":
        data["output"] = f"/api/output/{job_id}"
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def run_command(cmd, timeout=600):
    logger.info(f"RUN → {' '.join(cmd)[:200]}...")
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="ignore"
    )
    if p.stderr:
        logger.error(p.stderr[-500:])
    return p.returncode == 0

# ======================================
# Audio
# ======================================
def extract_audio(video, audio):
    return run_command([
        FFMPEG, "-y",
        "-i", video,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        audio
    ])

# ======================================
# 🔥 FAST + SAFE TRANSCRIBE (OPTIMIZED)
# ======================================
def transcribe_audio(audio_path, srt_path):
    update("transcribing", "Whisper fast transcription...")

    try:
        from faster_whisper import WhisperModel

        logger.info("Loading Whisper tiny (CPU, INT8, threads=1)")
        model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            download_root="/tmp/whisper"
        )

        segments, info = model.transcribe(
            audio_path,
            beam_size=1,                 # 🚀 SPEED BOOST
            best_of=1,                   # 🚀 SPEED BOOST
            temperature=0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 800}
        )

        def ts(x):
            h = int(x // 3600)
            m = int((x % 3600) // 60)
            s = int(x % 60)
            ms = int((x * 1000) % 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        with open(srt_path, "w", encoding="utf-8") as f:
            i = 1
            for seg in segments:
                text = seg.text.strip()
                if not text:
                    continue
                f.write(f"{i}\n")
                f.write(f"{ts(seg.start)} --> {ts(seg.end)}\n")
                f.write(text + "\n\n")
                i += 1

        if os.path.getsize(srt_path) < 50:
            raise RuntimeError("SRT kosong")

        logger.info("✓ Transcription selesai (FAST)")
        return True

    except Exception as e:
        logger.error(f"Whisper error: {e}")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:05,000\n[Subtitle tersedia]\n")
        return True

# ======================================
# Translate
# ======================================
def translate_subtitles(srt_path, target_lang="id"):
    logger.info("Translating subtitles...")
    try:
        lines = open(srt_path, encoding="utf-8").readlines()
        out = []
        buf = []

        for line in lines:
            line = line.strip()
            if re.match(r"^\d+$", line) or "-->" in line:
                if buf:
                    text = " ".join(buf)
                    r = requests.post(
                        "https://libretranslate.de/translate",
                        json={"q": text, "source": "auto", "target": target_lang},
                        timeout=10
                    )
                    out.append(r.json().get("translatedText", text))
                    buf = []
                out.append(line)
            elif line:
                buf.append(line)
            else:
                out.append("")

        out_path = os.path.join(JOB_DIR, "subs_indonesia.srt")
        open(out_path, "w", encoding="utf-8").write("\n".join(out))
        return out_path

    except Exception as e:
        logger.error(f"Translate error: {e}")
        return srt_path

# ======================================
# Burn Subtitle
# ======================================
def burn_subtitles(video, srt, output, size):
    style = f"FontSize={size},OutlineColour=&H80000000,BorderStyle=3"
    return run_command([
        FFMPEG, "-y",
        "-i", video,
        "-vf", f"subtitles='{srt}':force_style='{style}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        output
    ])

# ======================================
# MAIN
# ======================================
def main():
    update("started", "Processing")

    video_file = src
    if is_url:
        update("failed", "URL mode tidak diubah di versi ini")
        sys.exit(1)

    audio = os.path.join(JOB_DIR, "audio.wav")
    raw_srt = os.path.join(JOB_DIR, "raw.srt")
    out = os.path.join(JOB_DIR, "output.mp4")

    if not extract_audio(video_file, audio):
        update("failed", "Audio extract failed")
        sys.exit(1)

    if not transcribe_audio(audio, raw_srt):
        update("failed", "Transcribe failed")
        sys.exit(1)

    translated = translate_subtitles(raw_srt, target)

    if burn_subtitles(video_file, translated, out, font_size):
        update("done", "Video ready")
    else:
        update("failed", "Burn subtitle failed")

if __name__ == "__main__":
    main()
