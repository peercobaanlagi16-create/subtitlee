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
import tempfile
from http.cookies import SimpleCookie
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
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
# COOKIES FROM SECRET - DIPERBAIKI
# ======================================
def setup_cookies():
    """Setup cookies dari environment variable dengan format yang benar"""
    secret = os.getenv("COOKIES_TXT", "").strip()
    
    if not secret or len(secret) < 50:
        logger.warning("COOKIES_TXT tidak ditemukan atau terlalu pendek")
        return None
    
    logger.info(f"COOKIES_TXT length: {len(secret)} chars")
    
    # Simpan ke file dengan format Netscape
    with open(COOKIES_TEMP, "w", encoding="utf-8") as f:
        # Pastikan ada header
        if not secret.startswith('# Netscape HTTP Cookie File'):
            f.write('# Netscape HTTP Cookie File\n')
            f.write('# https://curl.haxx.se/rfc/cookie_spec.html\n')
            f.write('# This is a generated file! Do not edit.\n\n')
        f.write(secret)
    
    # Verifikasi cookies bisa dibaca
    try:
        cookie_count = 0
        with open(COOKIES_TEMP, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        cookie_count += 1
        
        logger.info(f"✓ Cookies file created with {cookie_count} cookies")
        return COOKIES_TEMP
        
    except Exception as e:
        logger.error(f"Error verifying cookies: {e}")
        return None

COOKIES_PATH = setup_cookies()

# ======================================
# Helper Functions
# ======================================
def update(status, log_msg=""):
    """Update status job"""
    data = {"status": status, "log": log_msg}
    if status == "done":
        data["output"] = f"/api/output/{job_id}"
    try:
        with open(STATUS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Status write error: {e}")

def run_command(cmd, timeout=300):
    """Run shell command dengan logging yang baik"""
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
    else:
        cmd_str = cmd
    
    logger.info(f"RUN → {cmd_str[:200]}...")
    
    try:
        process = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            cwd=APP_DIR,
            timeout=timeout,
            encoding='utf-8',
            errors='ignore'
        )
        
        if process.stdout:
            output = process.stdout.strip()
            if output:
                logger.info(f"STDOUT: {output[-500:]}")
        
        if process.stderr:
            error = process.stderr.strip()
            if error:
                logger.error(f"STDERR: {error[-500:]}")
        
        logger.info(f"Exit code: {process.returncode}")
        return process.returncode
        
    except subprocess.TimeoutExpired:
        logger.error(f"Command timeout after {timeout}s")
        return -1
    except Exception as e:
        logger.error(f"Command error: {e}")
        return -1

def find_video_file(job_dir):
    """Cari file video di directory job"""
    video_extensions = ['.mp4', '.mkv', '.webm', '.flv', '.avi', '.mov', '.wmv']
    
    for ext in video_extensions:
        for f in glob.glob(os.path.join(job_dir, f"*{ext}")):
            if any(x in f.lower() for x in ['.part', '.temp', '.ytdl', '.frag', '.tmp']):
                continue
            if os.path.getsize(f) > 1_000_000:  # > 1MB
                logger.info(f"Found video file: {f} ({os.path.getsize(f)/1024/1024:.2f} MB)")
                return f
    
    return None

# ======================================
# EPORNER SCRAPER - METODE 1: Direct MP4
# ======================================
def scrape_eporner_direct(url):
    """Cari URL MP4 langsung di halaman"""
    logger.info("Trying direct MP4 scraping...")
    
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    ]
    
    headers_base = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    
    for idx, ua in enumerate(user_agents, 1):
        logger.info(f"Scraping attempt {idx} with UA: {ua[:50]}...")
        
        headers = headers_base.copy()
        headers["User-Agent"] = ua
        
        try:
            # Buat session dengan cookies
            session = requests.Session()
            
            # Load cookies jika ada
            if COOKIES_PATH and os.path.exists(COOKIES_PATH):
                try:
                    with open(COOKIES_PATH, 'r') as f:
                        cookies_text = f.read()
                    
                    # Parse cookies Netscape format
                    for line in cookies_text.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#'):
                            parts = line.split('\t')
                            if len(parts) >= 7:
                                domain = parts[0].lstrip('.')
                                path = parts[2]
                                secure = parts[3] == 'TRUE'
                                name = parts[5]
                                value = parts[6]
                                
                                # Set cookie ke session
                                session.cookies.set(
                                    name=name,
                                    value=value,
                                    domain=domain,
                                    path=path
                                )
                    
                    logger.info(f"Loaded {len(session.cookies)} cookies")
                except Exception as e:
                    logger.warning(f"Could not load cookies: {e}")
            
            # Fetch halaman
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            html = response.text
            
            # Simpan untuk debugging
            debug_file = os.path.join(JOB_DIR, f"debug_{idx}.html")
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(html[:50000])
            
            # Regex patterns untuk mencari URL video
            patterns = [
                # Pattern 1: Video source tags
                r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\'][^>]*>',
                r'<video[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\'][^>]*>',
                
                # Pattern 2: Data attributes
                r'data-(?:src|video|mp4)=["\']([^"\']+\.mp4[^"\']*)["\']',
                
                # Pattern 3: JSON data
                r'"url"\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
                r'"src"\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
                r'"videoUrl"\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
                r'"file"\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
                r'"mp4"\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
                
                # Pattern 4: Direct MP4 URLs
                r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)',
                
                # Pattern 5: CDN URLs
                r'(https?://cdn[0-9]*\.eporner\.com/[^"\'\s<>]+\.mp4)',
                r'(https?://video[0-9]*\.eporner\.com/[^"\'\s<>]+\.mp4)',
                
                # Pattern 6: Hash-based URLs
                r'hash["\']?\s*:\s*["\']([a-fA-F0-9]+)["\']',
                r'videoHash["\']?\s*:\s*["\']([a-fA-F0-9]+)["\']',
            ]
            
            found_urls = []
            found_hashes = []
            
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    if 'hash' in pattern.lower():
                        found_hashes.extend(matches)
                        logger.info(f"Found {len(matches)} hash(es) with pattern: {pattern[:50]}...")
                    else:
                        found_urls.extend(matches)
                        logger.info(f"Found {len(matches)} URL(s) with pattern: {pattern[:50]}...")
            
            # Jika dapat hash, coba bangun URL
            for hash_val in found_hashes[:3]:
                # Coba format URL berdasarkan hash
                possible_formats = [
                    f"https://cdn.eporner.com/video/{hash_val}/video.mp4",
                    f"https://cdn1.eporner.com/video/{hash_val}/video.mp4",
                    f"https://cdn2.eporner.com/video/{hash_val}/video.mp4",
                    f"https://cdn3.eporner.com/video/{hash_val}/video.mp4",
                    f"https://video.eporner.com/{hash_val}.mp4",
                    f"https://videos.eporner.com/{hash_val}/video.mp4",
                    f"https://www.eporner.com/video/{hash_val}/video.mp4",
                ]
                
                for test_url in possible_formats:
                    try:
                        head_resp = session.head(test_url, headers=headers, timeout=5)
                        if head_resp.status_code == 200:
                            found_urls.append(test_url)
                            logger.info(f"✓ Valid URL from hash: {test_url}")
                    except:
                        continue
            
            # Filter dan deduplicate
            valid_urls = []
            for url_found in set(found_urls):
                if not url_found.startswith('http'):
                    if url_found.startswith('//'):
                        url_found = 'https:' + url_found
                    elif url_found.startswith('/'):
                        url_found = 'https://www.eporner.com' + url_found
                
                if url_found.startswith('http') and '.mp4' in url_found.lower():
                    valid_urls.append(url_found)
            
            if not valid_urls:
                logger.warning(f"No valid video URLs found in attempt {idx}")
                continue
            
            logger.info(f"Found {len(valid_urls)} potential video URLs")
            
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
                
                # Bonus untuk CDN dan direct links
                if 'cdn' in url_lower:
                    score += 200
                if 'video' in url_lower:
                    score += 100
                if 'download' in url_lower:
                    score += 50
                
                return score
            
            valid_urls.sort(key=get_quality_score, reverse=True)
            best_url = valid_urls[0]
            
            logger.info(f"Selected URL: {best_url[:200]}...")
            
            # Download video
            video_path = os.path.join(JOB_DIR, f"video_{idx}.mp4")
            
            # Gunakan curl untuk download (lebih reliable)
            curl_cmd = [
                'curl', '-L',
                '--max-time', '600',
                '--connect-timeout', '30',
                '--retry', '5',
                '--retry-delay', '2',
                '--retry-max-time', '1200',
                '--compressed',
                '--progress-bar',
                '-H', f'User-Agent: {ua}',
                '-H', f'Referer: {url}',
                '-H', 'Accept: */*',
                '-H', 'Accept-Language: en-US,en;q=0.9',
                '-H', 'Origin: https://www.eporner.com',
                '-o', video_path,
                best_url
            ]
            
            # Tambahkan cookies jika ada
            if COOKIES_PATH and os.path.exists(COOKIES_PATH):
                curl_cmd.extend(['-b', COOKIES_PATH])
            
            logger.info(f"Downloading with curl...")
            return_code = run_command(curl_cmd, timeout=900)
            
            if return_code == 0 and os.path.exists(video_path) and os.path.getsize(video_path) > 5_000_000:
                size_mb = os.path.getsize(video_path) / (1024 * 1024)
                logger.info(f"✓ Download successful! Size: {size_mb:.2f} MB")
                return video_path
            
            # Cleanup
            if os.path.exists(video_path):
                os.remove(video_path)
                
        except Exception as e:
            logger.error(f"Error in attempt {idx}: {e}")
            continue
        
        time.sleep(2)
    
    return None

# ======================================
# EPORNER SCRAPER - METODE 2: yt-dlp dengan workaround
# ======================================
def download_with_ytdlp_workaround(url):
    """Coba yt-dlp dengan berbagai workaround"""
    logger.info("Trying yt-dlp with workarounds...")
    
    video_path = os.path.join(JOB_DIR, "video_ytdlp.mp4")
    
    # Base command untuk yt-dlp
    base_cmd = [
        'yt-dlp',
        '-o', video_path,
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        '--referer', url,
        '--socket-timeout', '60',
        '--retries', '10',
        '--fragment-retries', '10',
        '--skip-unavailable-fragments',
        '--concurrent-fragments', '4',
        '--throttled-rate', '100K',
        '--force-ipv4',
    ]
    
    # Tambahkan cookies jika ada
    if COOKIES_PATH and os.path.exists(COOKIES_PATH):
        base_cmd.extend(['--cookies', COOKIES_PATH])
    
    # Coba berbagai format dan options
    strategies = [
        # Strategy 1: Format terbaik
        ['-f', 'best[height<=1080]'],
        
        # Strategy 2: Format MP4 terbaik
        ['-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'],
        
        # Strategy 3: Tanpa format spec
        [],
        
        # Strategy 4: Dengan extractor args
        ['--extractor-args', 'eporner:hash_workaround'],
        
        # Strategy 5: Generic extractor
        ['--force-generic-extractor'],
        
        # Strategy 6: Dengan verbose logging
        ['-v', '--no-check-certificate'],
    ]
    
    for i, strategy in enumerate(strategies, 1):
        logger.info(f"yt-dlp strategy {i}/{len(strategies)}")
        
        cmd = base_cmd + strategy + [url]
        
        # Hapus file lama jika ada
        if os.path.exists(video_path):
            os.remove(video_path)
        
        return_code = run_command(cmd, timeout=600)
        
        # Cek hasil
        found_video = find_video_file(JOB_DIR)
        if found_video:
            # Rename ke video_path jika berbeda
            if found_video != video_path:
                if os.path.exists(video_path):
                    os.remove(video_path)
                os.rename(found_video, video_path)
            
            if os.path.exists(video_path) and os.path.getsize(video_path) > 5_000_000:
                logger.info(f"✓ yt-dlp strategy {i} successful!")
                return video_path
        
        time.sleep(3)
    
    return None

# ======================================
# DOWNLOAD UTAMA
# ======================================
def download_video(url):
    """Main download function dengan multiple fallbacks"""
    logger.info(f"Starting download for: {url}")
    
    # Coba metode yang berbeda
    methods = [
        ("Direct MP4 Scraping", scrape_eporner_direct),
        ("yt-dlp Workaround", download_with_ytdlp_workaround),
    ]
    
    for method_name, method_func in methods:
        logger.info(f"Trying method: {method_name}")
        update("downloading", f"Trying {method_name}...")
        
        result = method_func(url)
        if result:
            # Final video path
            final_path = os.path.join(JOB_DIR, "video.mp4")
            
            # Jika result bukan final_path, rename
            if result != final_path:
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(result, final_path)
            
            if os.path.exists(final_path) and os.path.getsize(final_path) > 5_000_000:
                size_mb = os.path.getsize(final_path) / (1024 * 1024)
                logger.info(f"✓ Download SUCCESSFUL! Method: {method_name}, Size: {size_mb:.2f} MB")
                return final_path
        
        logger.warning(f"Method {method_name} failed")
    
    # Semua metode gagal
    logger.error("All download methods failed")
    return None

# ======================================
# PROCESSING FUNCTIONS (Audio, Transcribe, Translate, Burn)
# ======================================
def extract_audio(video_path, audio_path):
    """Extract audio dari video"""
    logger.info(f"Extracting audio from {video_path}")
    
    cmd = [
        FFMPEG, '-y', '-i', video_path,
        '-vn', '-ac', '1', '-ar', '16000',
        '-acodec', 'pcm_s16le',
        '-loglevel', 'quiet',
        '-hide_banner',
        audio_path
    ]
    
    return run_command(cmd) == 0

def transcribe_audio(audio_path, srt_path):
    """Transcribe audio menggunakan Whisper"""
    update("transcribing", "Running Whisper transcription...")
    
    try:
        from faster_whisper import WhisperModel
        
        logger.info("Loading Whisper model (small)...")
        model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8",
            download_root="/tmp/whisper"
        )
        
        logger.info("Starting transcription...")
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            best_of=5,
            patience=1,
            temperature=0,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=False
        )
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        
        # Write SRT file
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, 1):
                start = segment.start
                end = segment.end
                text = segment.text.strip()
                
                # Format SRT timestamp
                def format_time(seconds):
                    hours = int(seconds // 3600)
                    minutes = int((seconds % 3600) // 60)
                    secs = int(seconds % 60)
                    millis = int((seconds * 1000) % 1000)
                    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
                
                start_str = format_time(start)
                end_str = format_time(end)
                
                f.write(f"{i}\n{start_str} --> {end_str}\n{text}\n\n")
        
        logger.info(f"Transcription saved to {srt_path}")
        return True
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def translate_subtitles(srt_path, target_lang):
    """Translate subtitles ke bahasa target"""
    logger.info(f"Translating subtitles to {target_lang}")
    
    try:
        subs = pysubs2.load(srt_path)
        
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target=target_lang)
        
        total = len(subs)
        for i, line in enumerate(subs):
            if line.text.strip():
                try:
                    translated = translator.translate(line.text.strip())
                    line.text = translated
                    
                    if (i + 1) % 20 == 0:
                        logger.info(f"Translated {i+1}/{total} lines")
                except Exception as e:
                    logger.warning(f"Translation error line {i+1}: {e}")
                    continue
        
        translated_path = os.path.join(JOB_DIR, "subs_translated.srt")
        subs.save(translated_path)
        
        logger.info(f"Translation completed: {translated_path}")
        return translated_path
        
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        # Return original if translation fails
        return srt_path

def burn_subtitles(video_path, srt_path, output_path, font_size):
    """Burn subtitles ke video"""
    logger.info(f"Burning subtitles with size {font_size}")
    
    # Escape path untuk filter
    srt_escaped = srt_path.replace("'", "'\\''")
    
    # Style untuk subtitles
    style = (
        f"FontSize={font_size},"
        f"OutlineColour=&H80000000,"
        f"BorderStyle=3,"
        f"BackColour=&H80000000,"
        f"Alignment=2,"
        f"MarginV=30,"
        f"FontName=Arial,"
        f"PrimaryColour=&H00FFFFFF,"
        f"Outline=1,"
        f"Shadow=0"
    )
    
    cmd = [
        FFMPEG, '-y',
        '-i', video_path,
        '-vf', f"subtitles='{srt_escaped}':force_style='{style}'",
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '23',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-loglevel', 'error',
        '-hide_banner',
        output_path
    ]
    
    success = run_command(cmd, timeout=600) == 0
    
    if success and os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"✓ Subtitles burned successfully! Output: {size_mb:.2f} MB")
    
    return success

# ======================================
# MAIN PROCESS
# ======================================
def main():
    """Main processing pipeline"""
    logger.info("=" * 60)
    logger.info(f"JOB STARTED: {job_id}")
    logger.info(f"Source: {src}")
    logger.info(f"Target language: {target}")
    logger.info(f"Is URL: {is_url}")
    logger.info(f"Font size: {font_size}")
    logger.info("=" * 60)
    
    update("started", "Processing started")
    
    # Step 1: Parse URL
    final_url = src.strip() if is_url else src
    if is_url and not final_url.startswith("http"):
        url_match = re.search(r'src=[\'"]([^\'"]+)', src)
        final_url = url_match.group(1) if url_match else src
    
    logger.info(f"Processing URL: {final_url}")
    
    # Step 2: Download video
    update("downloading", "Downloading video...")
    video_file = download_video(final_url)
    
    if not video_file:
        update("failed", "Video download failed")
        logger.error("❌ Download failed!")
        sys.exit(1)
    
    # Step 3: Extract audio
    update("processing", "Extracting audio...")
    audio_file = os.path.join(JOB_DIR, "audio.wav")
    
    if not extract_audio(video_file, audio_file):
        update("failed", "Audio extraction failed")
        sys.exit(1)
    
    # Step 4: Transcribe
    update("transcribing", "Transcribing audio...")
    raw_srt = os.path.join(JOB_DIR, "raw.srt")
    
    if not transcribe_audio(audio_file, raw_srt):
        update("failed", "Transcription failed")
        sys.exit(1)
    
    # Step 5: Translate
    update("translating", "Translating subtitles...")
    translated_srt = translate_subtitles(raw_srt, target)
    
    # Step 6: Burn subtitles
    update("burning", "Burning subtitles to video...")
    output_file = os.path.join(JOB_DIR, "output.mp4")
    
    if burn_subtitles(video_file, translated_srt, output_file, font_size):
        update("done", "Video ready for download!")
        logger.info(f"✅ JOB COMPLETED: {job_id}")
        logger.info(f"Output file: {output_file}")
    else:
        update("failed", "Failed to burn subtitles")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        update("cancelled", "Process cancelled")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        update("failed", f"Unexpected error: {str(e)}")
        sys.exit(1)