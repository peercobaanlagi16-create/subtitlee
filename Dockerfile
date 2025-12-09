# Dockerfile — FINAL & 100% CLEAN untuk Koyeb (Desember 2025)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install semua dependency sistem dalam 1 layer biar cepat + bersih
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

# Install yt-dlp versi terbaru (WAJIB selalu fresh!)
RUN pip install --no-cache-dir --upgrade yt-dlp

WORKDIR /app

# Copy requirements dulu (caching)
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Optional: av dari system libs
RUN pip install --no-cache-dir av==11.0.0 || true

# Install onnxruntime + faster-whisper tanpa deps
RUN pip install --no-cache-dir onnxruntime==1.15.1
RUN pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# Copy source code
COPY . .

# Pastikan yt-dlp jalan
RUN yt-dlp --version

EXPOSE 8000

# Uvicorn dengan 1 worker (cukup, karena worker.py sudah background)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]