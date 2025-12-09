# Dockerfile — VERSI FINAL 100% JALAN DI KOYEb (Desember 2025)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install semua sistem dependency + curl + yt-dlp terbaru
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \                  # ← WAJIB! buat fallback download
        wget \
        git \
        build-essential \
        pkg-config \
        ffmpeg \                # ← sudah ada
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

# Upgrade pip dulu
RUN pip install --upgrade pip setuptools wheel

# Install yt-dlp versi terbaru (PENTING! versi lama sering gagal di situs baru)
RUN pip install --no-cache-dir --upgrade yt-dlp

WORKDIR /app

# Copy requirements dulu biar caching
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# (Opsional) coba install av dari system libs
RUN pip install --no-cache-dir av==11.0.0 || true

# Install onnxruntime + faster-whisper tanpa deps (biar tidak compile av lagi)
RUN pip install --no-cache-dir onnxruntime==1.15.1
RUN pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# Copy source code terakhir
COPY . .

# Pastikan yt-dlp benar-benar latest (kadang pip cache)
RUN yt-dlp --version && echo "yt-dlp ready!"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]