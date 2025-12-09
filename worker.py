#!/usr/bin/env python3
import os, sys, json, subprocess, re, time, glob, logging

# NOTE: do not import faster_whisper or libretranslatepy at top-level
# because they may pull in binary deps (av) and crash the process during import.
# We'll import them lazily inside the functions that need them.

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
PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or None

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
        logging.error("Failed to write status.json: " + str(e))

def run(cmd):
    logging.info("RUN: " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
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

def extract_src(embed):
    m = re.search(r'src=[\'"]([^\'"]+)', embed)
    return m.group(1) if m else embed

def find_downloaded_video(job_dir):
    for pattern in [os.path.join(job_dir, "video.*"), os.path.join(job_dir, "*.*")]:
        for f in glob.glob(pattern):
            if any(x in f for x in [".part", ".temp", ".ytdl"]):
                continue
            try:
                size = os.path.getsize(f)
            except Exception:
                continue
            if size > 100000:
                return f
            else:
                try: os.remove(f)
                except: pass
    return None

# ======================================
# Download Video
# ======================================
def download_video(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = 'Mozilla/5.0'

    commands = [
        f'yt-dlp -o "{video_path}" "{url}" -f "best[height<=720]"',
        f'yt-dlp -o "{video_path}" "{url}" -f "best"'
    ]

    for i, cmd in enumerate(commands):
        update("downloading", f"Download attempt {i+1}/2")
        rc = run(cmd)
        file = find_downloaded_video(JOB_DIR)
        if file:
            return file
        time.sleep(2)

    return None

# ======================================
# Extract Audio
# ======================================
def extract_audio(video, out):
    cmd = f'{FFMPEG} -y -i "{video}" -vn -ac 1 -ar 16000 -acodec pcm_s16le "{out}"'
    return run(cmd) == 0

# ======================================
# TRANSCRIBE with faster-whisper (lazy import)
# ======================================
def transcribe(audio_path, output_srt):
    update("transcribing", "Initializing transcription model...")

    # Lazy import for faster_whisper to avoid crash if av not installed
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        logging.error("Failed to import faster_whisper: " + str(e))
        update("failed", "Missing faster_whisper or binary deps (av). Check Docker/requirements.")
        return False

    try:
        model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8"
        )
    except Exception as e:
        logging.error("Failed to init WhisperModel: " + str(e))
        update("failed", f"Whisper model init error: {e}")
        return False

    update("transcribing", "Transcribing audio...")

    try:
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            best_of=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=300
            )
        )
    except Exception as e:
        logging.error("Error during transcribe: " + str(e))
        update("failed", f"Transcribe error: {e}")
        return False

    # Build SRT file
    try:
        with open(output_srt, "w", encoding="utf-8") as srt:
            idx = 1
            for seg in segments:
                start = seg.start
                end = seg.end
                text = seg.text.strip()
                srt.write(f"{idx}\n")
                srt.write("%02d:%02d:%02d,%03d --> %02d:%02d:%02d,%03d\n" % (
                    int(start // 3600),
                    int((start % 3600) // 60),
                    int(start % 60),
                    int((start * 1000) % 1000),
                    int(end // 3600),
                    int((end % 3600) // 60),
                    int(end % 60),
                    int((end * 1000) % 1000),
                ))
                srt.write(text + "\n\n")
                idx += 1
    except Exception as e:
        logging.error("Failed to write SRT: " + str(e))
        update("failed", f"Write SRT error: {e}")
        return False

    return os.path.exists(output_srt)

# ======================================
# Translate SRT (lazy import)
# ======================================
def translate_srt(path, target):
    subs = pysubs2.load(path)
    count = 0

    # Try deep_translator.GoogleTranslator first
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target=target)
        for line in subs:
            if line.text.strip():
                try:
                    translated = translator.translate(line.text.strip())
                    line.text = translated.strip()
                    count += 1
                    if count % 20 == 0:
                        update("translating", f"Translated {count} lines...")
                        logging.info(f"Translated {count} lines")
                except Exception as e:
                    logging.error(f"Error translating a line: {e}")
                    continue
        update("translating", f"Translated {count} lines... Done!")
    except Exception as e:
        logging.error("Translator initialization failed: " + str(e))
        # If translator not available, we keep original SRT and proceed

    out = os.path.join(JOB_DIR, "subs.srt")
    subs.save(out)
    return out

# ======================================
# Burn subtitle
# ======================================
def escape(path):
    p = path.replace("\\", "/")
    p = p.replace(":", "\\:")
    return p

def burn(video, srt, out, size):
    vf = (
        f"subtitles='{escape(srt)}':force_style="
        f"'FontSize={size},OutlineColour=&H80000000,BorderStyle=3,BackColour=&H80000000'"
    )
    cmd = [
        FFMPEG, "-y", "-i", video,
        "-vf", vf, "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        out
    ]
    return run(cmd) == 0

# ======================================
# MAIN FLOW
# ======================================
update("started", "Starting...")

# If URL
if is_url:
    url = extract_src(src)
    video = download_video(url)
    if not video:
        update("failed", "Download error")
        sys.exit(1)
else:
    video = src

# Extract audio
audio = os.path.join(JOB_DIR, "audio.wav")
if not extract_audio(video, audio):
    update("failed", "Audio extraction error")
    sys.exit(1)

# Transcribe
raw_srt = os.path.join(JOB_DIR, "raw.srt")
if not transcribe(audio, raw_srt):
    # transcribe() already wrote failure status
    sys.exit(1)

# Translate
update("translating", "Starting translate...")
final_srt = translate_srt(raw_srt, target)

# Burn video
update("burning", "Burning subtitle...")
out_video = os.path.join(JOB_DIR, "output.mp4")

if burn(video, final_srt, out_video, font_size):
    update("done", "Completed")
else:
    update("failed", "Burn failed")
    sys.exit(1)
