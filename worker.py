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
from bs4 import BeautifulSoup

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

logger = logging.getLogger(__name__)
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# ======================================
# COOKIES FROM SECRET
# ======================================
def get_cookies_path():
    secret = os.getenv("COOKIES_TXT")
    logger.info(f"DEBUG: COOKIES_TXT env: {'EXISTS' if secret else 'MISSING'} | Length: {len(secret) if secret else 0}")
    if secret and len(secret.strip()) > 50:
        path = os.path.join(JOB_DIR, "cookies_from_secret.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(secret.strip())
        logger.info("SUCCESS: Cookies loaded from Koyeb Secret!")
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
        logger.error(f"Status write error: {e}")

def run(cmd):
    logger.info("RUN → " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, cwd=APP_DIR)
    if p.stdout: 
        logger.info(p.stdout[-1500:])
    if p.stderr: 
        logger.error(p.stderr[-1500:])
    return p.returncode

def find_video(job_dir):
    for f in glob.glob(os.path.join(job_dir, "*.*")):
        if any(x in f for x in [".part", ".temp", ".ytdl", ".frag"]): 
            continue
        if os.path.getsize(f) > 500_000:
            return f
    return None

# ======================================
# EPORNER MANUAL SCRAPER (UPDATED Des 2025)
# ======================================
def download_eporner(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    headers = {
        "User-Agent": ua,
        "Referer": url,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }

    update("downloading", "Eporner: Manual scrape with cookies...")
    
    try:
        session = requests.Session()
        if COOKIES_PATH:
            with open(COOKIES_PATH, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split('\t')
                        if len(parts) >= 7:
                            domain, _, path, secure, expires, name, value = parts[:7]
                            session.cookies.set(name, value, domain=domain, path=path)
            logger.info(f"Loaded {len(session.cookies)} cookies")

        # Fetch halaman
        logger.info(f"Fetching: {url}")
        resp = session.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.error(f"Failed to load page: {resp.status_code}")
            return None

        html = resp.text
        
        # Simpan HTML untuk debugging
        debug_file = os.path.join(JOB_DIR, "eporner_debug.html")
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(html[:100000])
        
        # Parse dengan BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        
        video_urls = []
        
        # METHOD 1: Cari semua tag video dan source
        for video_tag in soup.find_all('video'):
            if video_tag.get('src'):
                video_urls.append(video_tag['src'])
            for source_tag in video_tag.find_all('source'):
                if source_tag.get('src'):
                    video_urls.append(source_tag['src'])
        
        # METHOD 2: Cari data-src attributes
        for tag in soup.find_all(attrs={"data-src": True}):
            src = tag.get('data-src')
            if src and '.mp4' in src:
                video_urls.append(src)
        
        # METHOD 3: Cari dalam script tags untuk JSON data
        for script in soup.find_all('script'):
            if script.string:
                content = script.string
                # Cari URL MP4 dalam script
                mp4_patterns = [
                    r'"url"\s*:\s*"([^"]+\.mp4[^"]*)"',
                    r'"src"\s*:\s*"([^"]+\.mp4[^"]*)"',
                    r'"videoUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
                    r'"file"\s*:\s*"([^"]+\.mp4[^"]*)"',
                    r'"mp4"\s*:\s*"([^"]+\.mp4[^"]*)"',
                    r'https?://[^"\']+\.mp4[^"\']*'
                ]
                for pattern in mp4_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    video_urls.extend(matches)
        
        # METHOD 4: Cari langsung dengan regex di HTML
        direct_mp4_urls = re.findall(r'https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*', html)
        video_urls.extend(direct_mp4_urls)
        
        # METHOD 5: Cari embed atau iframe src
        for iframe in soup.find_all(['iframe', 'embed']):
            src = iframe.get('src')
            if src and 'mp4' in src.lower():
                video_urls.append(src)
        
        # Filter dan deduplicate
        video_urls = list(set([url.strip() for url in video_urls if url and 'http' in url]))
        
        logger.info(f"Found {len(video_urls)} potential video URLs")
        
        if not video_urls:
            logger.error("No video sources found with any method")
            
            # Coba ekstrak dengan regex fallback
            fallback_patterns = [
                r'data-video-url=["\']([^"\']+)["\']',
                r'video-url=["\']([^"\']+)["\']',
                r'<a[^>]+href=["\']([^"\']+\.mp4)["\'][^>]*>',
                r'window\.location\.href\s*=\s*["\']([^"\']+\.mp4)["\']'
            ]
            
            for pattern in fallback_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    video_urls.extend(matches)
                    logger.info(f"Found {len(matches)} with pattern: {pattern}")
        
        if not video_urls:
            return None
        
        # Pilih URL terbaik berdasarkan kualitas
        def get_quality_score(url):
            url_lower = url.lower()
            score = 0
            if '1080' in url_lower or 'hd1080' in url_lower:
                score = 1000
            elif '720' in url_lower or 'hd720' in url_lower:
                score = 700
            elif '480' in url_lower:
                score = 400
            elif '360' in url_lower:
                score = 100
            elif 'hd' in url_lower:
                score = 500
            if 'high' in url_lower:
                score += 200
            if 'quality' in url_lower:
                score += 100
            return score
        
        video_urls.sort(key=get_quality_score, reverse=True)
        best_url = video_urls[0]
        
        # Fix URL jika perlu
        if best_url.startswith('//'):
            best_url = 'https:' + best_url
        elif best_url.startswith('/'):
            best_url = 'https://www.eporner.com' + best_url
        elif not best_url.startswith('http'):
            best_url = 'https://' + best_url
        
        logger.info(f"Selected best URL: {best_url[:200]}...")
        
        # Download dengan curl (paling reliable)
        curl_cmd = [
            'curl', '-L', 
            '--max-time', '600',
            '--connect-timeout', '30',
            '--retry', '3',
            '--retry-delay', '5',
            '-H', f'User-Agent: {ua}',
            '-H', f'Referer: {url}',
            '-H', 'Accept: */*',
            '-H', 'Accept-Language: en-US,en;q=0.9',
            '-H', 'Accept-Encoding: gzip, deflate',
            '-H', 'DNT: 1',
            '-H', 'Connection: keep-alive',
            '-H', 'Upgrade-Insecure-Requests: 1',
            '-o', video_path,
            best_url
        ]
        
        if COOKIES_PATH:
            curl_cmd.extend(['-b', COOKIES_PATH])
        
        logger.info("Downloading with curl...")
        update("downloading", "Downloading video...")
        
        if run(curl_cmd) == 0:
            if os.path.exists(video_path) and os.path.getsize(video_path) > 500_000:
                file_size = os.path.getsize(video_path) / (1024*1024)
                logger.info(f"EPORNER SUCCESS! File size: {file_size:.2f} MB")
                return video_path
            else:
                logger.error(f"File too small or missing: {video_path}")
        else:
            logger.error("Curl download failed")
            
        # Fallback ke wget
        logger.info("Trying wget fallback...")
        wget_cmd = f'wget -O "{video_path}" "{best_url}" --user-agent="{ua}" --header="Referer: {url}"'
        if COOKIES_PATH:
            wget_cmd += f' --load-cookies="{COOKIES_PATH}"'
        
        if run(wget_cmd) == 0 and os.path.getsize(video_path) > 500_000:
            logger.info("EPORNER SUCCESS via wget!")
            return video_path
        
    except Exception as e:
        logger.error(f"Eporner scrape error: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return None

# ======================================
# DOWNLOAD UTAMA
# ======================================
def download_video(url):
    video_path = os.path.join(JOB_DIR, "video.mp4")
    
    # Coba eporner manual scraper dulu
    if "eporner.com" in url.lower():
        logger.info("Detected eporner.com URL, using manual scraper")
        result = download_eporner(url)
        if result:
            return result
        logger.info("Manual scraper failed, trying yt-dlp...")
    
    # Konfigurasi yt-dlp
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    
    # Build base command
    base_cmd = [
        'yt-dlp',
        '-o', video_path,
        '--user-agent', ua,
        '--referer', url,
        '--retries', '10',
        '--socket-timeout', '30',
        '--source-address', '0.0.0.0',
    ]
    
    if COOKIES_PATH:
        base_cmd.extend(['--cookies', COOKIES_PATH])
    
    # Coba berbagai kombinasi options
    options_list = [
        ['--format', 'best[height<=1080]', '--concurrent-fragments', '8'],
        ['--format', 'best', '--no-check-certificate'],
        ['--format', 'best', '--force-generic-extractor'],
        ['--format', 'mp4', '--verbose'],
        []  # Default tanpa format spec
    ]
    
    for i, options in enumerate(options_list, 1):
        update("downloading", f"yt-dlp attempt {i}/{len(options_list)}...")
        cmd = base_cmd + options + [url]
        
        logger.info(f"Attempt {i}: yt-dlp with options {options}")
        if run(cmd) == 0:
            # Cari file video yang berhasil didownload
            for f in glob.glob(os.path.join(JOB_DIR, "*.*")):
                if any(ext in f for ext in ['.mp4', '.mkv', '.webm', '.flv', '.avi']):
                    if os.path.getsize(f) > 500_000:
                        if f != video_path:
                            os.rename(f, video_path)
                        logger.info(f"Download successful: {os.path.basename(video_path)}")
                        return video_path
        
        time.sleep(2)
    
    # Fallback terakhir: curl langsung
    logger.info("All yt-dlp attempts failed, trying direct curl...")
    update("downloading", "Trying direct download...")
    
    curl_cmd = [
        'curl', '-L',
        '--max-time', '300',
        '--retry', '3',
        '-A', ua,
        '-H', f'Referer: {url}',
        '-o', video_path,
        url
    ]
    
    if COOKIES_PATH:
        curl_cmd.extend(['-b', COOKIES_PATH])
    
    if run(curl_cmd) == 0 and os.path.getsize(video_path) > 500_000:
        logger.info("Direct curl download successful!")
        return video_path
    
    return None

# ======================================
# Extract, Transcribe, Translate, Burn
# ======================================
def extract_audio(v, o):
    logger.info(f"Extracting audio from {v}")
    cmd = [
        FFMPEG, '-y', '-i', v,
        '-vn', '-ac', '1', '-ar', '16000',
        '-acodec', 'pcm_s16le',
        '-loglevel', 'error',
        o
    ]
    return run(cmd) == 0

def transcribe(a, srt):
    update("transcribing", "Whisper running...")
    try:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper model...")
        model = WhisperModel("small", device="cpu", compute_type="int8")
        logger.info("Transcribing audio...")
        segments, info = model.transcribe(a, beam_size=5, vad_filter=True)
        
        logger.info(f"Detected language: {info.language}, probability: {info.language_probability}")
        
        with open(srt, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, 1):
                start = segment.start
                end = segment.end
                text = segment.text.strip()
                
                # Format waktu SRT
                start_str = f"{int(start // 3600):02d}:{int((start % 3600) // 60):02d}:{int(start % 60):02d},{int((start * 1000) % 1000):03d}"
                end_str = f"{int(end // 3600):02d}:{int((end % 3600) // 60):02d}:{int(end % 60):02d},{int((end * 1000) % 1000):03d}"
                
                f.write(f"{i}\n{start_str} --> {end_str}\n{text}\n\n")
        
        logger.info(f"Transcription saved to {srt}")
        return True
    except Exception as e:
        logger.error(f"Whisper failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def translate_srt(p, lang):
    logger.info(f"Translating subtitles to {lang}")
    subs = pysubs2.load(p)
    
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target=lang)
        
        total_lines = len(subs)
        for idx, line in enumerate(subs):
            if line.text.strip():
                try:
                    translated = translator.translate(line.text.strip())
                    line.text = translated
                    if idx % 10 == 0:
                        logger.info(f"Translated {idx}/{total_lines} lines")
                except Exception as e:
                    logger.warning(f"Failed to translate line {idx}: {e}")
                    # Keep original text if translation fails
    except Exception as e:
        logger.error(f"Translation setup failed: {e}")
        # Continue without translation
    
    out = os.path.join(JOB_DIR, "subs.srt")
    subs.save(out)
    logger.info(f"Translated subtitles saved to {out}")
    return out

def burn(v, s, o, size):
    logger.info(f"Burning subtitles with font size {size}")
    # Escape path for ffmpeg filter
    s_esc = s.replace("'", "'\\''")
    
    # Subtitles style
    style = (
        f"FontSize={size},"
        f"OutlineColour=&H80000000,"
        f"BorderStyle=3,"
        f"BackColour=&H80000000,"
        f"Alignment=2,"
        f"MarginV=30"
    )
    
    cmd = [
        FFMPEG, '-y',
        '-i', v,
        '-vf', f"subtitles='{s_esc}':force_style='{style}'",
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '23',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-loglevel', 'error',
        o
    ]
    
    return run(cmd) == 0

# ======================================
# MAIN
# ======================================
def main():
    logger.info("=" * 50)
    logger.info(f"Starting job: {job_id}")
    logger.info(f"Source: {src}")
    logger.info(f"Target lang: {target}")
    logger.info(f"Is URL: {is_url}")
    logger.info(f"Font size: {font_size}")
    logger.info("=" * 50)
    
    update("started", "Worker started")
    
    # Parse URL
    final_url = src.strip() if is_url else src
    if is_url and not final_url.startswith("http"):
        m = re.search(r'src=[\'"]([^\'"]+)', src)
        final_url = m.group(1) if m else src
    
    logger.info(f"Final URL: {final_url}")
    
    # 1. Download video
    update("downloading", "Downloading video...")
    video = download_video(final_url)
    if not video:
        update("failed", "Download failed - no video source found")
        logger.error("Download failed!")
        sys.exit(1)
    
    logger.info(f"Video downloaded: {video} ({os.path.getsize(video) / (1024*1024):.2f} MB)")
    
    # 2. Extract audio
    update("processing", "Extracting audio...")
    audio = os.path.join(JOB_DIR, "audio.wav")
    if not extract_audio(video, audio):
        update("failed", "Audio extraction failed")
        sys.exit(1)
    
    # 3. Transcribe
    update("transcribing", "Transcribing audio...")
    raw_srt = os.path.join(JOB_DIR, "raw.srt")
    if not transcribe(audio, raw_srt):
        update("failed", "Transcription failed")
        sys.exit(1)
    
    # 4. Translate
    update("translating", "Translating subtitles...")
    final_srt = translate_srt(raw_srt, target)
    
    # 5. Burn subtitles
    update("burning", "Burning subtitles to video...")
    output_path = os.path.join(JOB_DIR, "output.mp4")
    if burn(video, final_srt, output_path, font_size):
        update("done", "Video ready for download!")
        logger.info(f"Job completed successfully: {job_id}")
        logger.info(f"Output file: {output_path}")
    else:
        update("failed", "Failed to burn subtitles")
        sys.exit(1)

if __name__ == "__main__":
    main()