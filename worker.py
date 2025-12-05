#!/usr/bin/env python3
import os, sys, json, subprocess, re, time, glob, logging
from libretranslatepy import LibreTranslateAPI
from faster_whisper import WhisperModel
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
FFMPEG = "ffmpeg"
PROXY = None


# ======================================
# Helper
# ======================================
def update(status, log=""):
    data = {"status": status, "log": log}
    if status == "done":
        data["output"] = f"/api/output/{job_id}"
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        logging.info(p.stdout[-1000:])
    if p.stderr:
        logging.error(p.stderr[-1000:])
    return p.returncode


def extract_src(embed):
    m = re.search(r'src=[\'"]([^\'"]+)', embed)
    return m.group(1) if m else embed


def find_downloaded_video(job_dir):
    for pattern in [os.path.join(job_dir, "video.*"), os.path.join(job_dir, "*.*")]:
        for f in glob.glob(pattern):
            if any(x in f for x in [".part", ".temp", ".ytdl"]):
                continue
            size = os.path.getsize(f)
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

    base_opts = [
        '--no-playlist', '-4',
        f'--user-agent "{ua}"',
        '--no-part', '--ignore-errors',
        '--concurrent-fragments 3'
    ]

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
# TRANSCRIBE with Faster-Whisper tiny-int8
# ======================================
def transcribe(audio_path, output_srt):
    update("transcribing", "Downloading model tiny-int8 (first time only)...")

    model = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8"
    )

    update("transcribing", "Transcribing audio...")

    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        best_of=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,  # tambahkan parameter VAD
            speech_pad_ms=300
        )
    )

    # Build SRT file manually
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

    return os.path.exists(output_srt)


# ======================================
# Translate
# ======================================
def translate_srt(path, target):
    subs = pysubs2.load(path)
    
    try:
        from deep_translator import GoogleTranslator
        
        # Inisialisasi translator
        translator = GoogleTranslator(source='auto', target=target)
        
        count = 0
        for line in subs:
            if line.text.strip():
                try:
                    # Terjemahkan setiap baris
                    translated = translator.translate(line.text.strip())
                    line.text = translated.strip()
                    count += 1
                    
                    # Update status setiap 20 baris
                    if count % 20 == 0:
                        update("translating", f"Translated {count} lines...")
                        logging.info(f"Translated {count} lines")
                        
                except Exception as e:
                    logging.error(f"Error translating line: {e}")
                    continue
        
        update("translating", f"Translated {count} lines... Done!")
        
    except Exception as e:
        logging.error(f"Translator initialization failed: {e}")
        # Jika gagal, tetap gunakan subtitle asli (Inggris)
    
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
    update("failed", "Transcribe error")
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
