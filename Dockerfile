# Dockerfile — FINAL FIX EPORNER + BUILD SUCCESS 100% di Koyeb (Des 2025)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install sistem deps (termasuk curl untuk fallback)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        git \
        build-essential \
        pkg-config \
        ffmpeg \
        python3 \
        python3-pip \
        python3-dev \
        gcc \
        libavformat-dev \
        libavcodec-dev \
        libavdevice-dev \
        libavutil-dev \
        libavfilter-dev \
        libswscale-dev \
        libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Symlink python & pip
RUN ln -s /usr/bin/python3 /usr/local/bin/python && \
    ln -s /usr/bin/pip3 /usr/local/bin/pip

# Upgrade pip
RUN pip install --upgrade pip setuptools wheel

# Install yt-dlp TERBARU + curl_cffi (FIX EPORNER IMPERSONATE)
RUN pip install --no-cache-dir --upgrade \
    "yt-dlp[curl_cffi]"

WORKDIR /app

# Copy requirements (caching)
COPY requirements.txt .

# Install sisa packages
RUN pip install --no-cache-dir -r requirements.txt

# Optional av
RUN pip install --no-cache-dir av==11.0.0 || true

# faster-whisper dll
RUN pip install --no-cache-dir onnxruntime==1.15.1
RUN pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# Copy source
COPY . .

# Verify yt-dlp + curl_cffi
RUN yt-dlp --version && python -c "import curl_cffi; print('curl_cffi ready!')"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]