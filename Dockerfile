# Dockerfile — FINAL & AMAN 100% (NO cookies.txt di repo!)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

# Install deps sistem
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget git build-essential pkg-config ffmpeg \
        python3 python3-pip python3-dev gcc g++ \
        libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
        libavfilter-dev libswscale-dev libswresample-dev \
        libssl-dev libffi-dev libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Python symlink
RUN ln -s /usr/bin/python3 /usr/local/bin/python && \
    ln -s /usr/bin/pip3 /usr/local/bin/pip

# Upgrade pip
RUN pip install --upgrade pip setuptools wheel

# Install yt-dlp TERBARU (FIX untuk Eporner)
RUN pip install --upgrade git+https://github.com/yt-dlp/yt-dlp.git@master

# Install curl_cffi untuk impersonate Chrome
RUN pip install --no-cache-dir curl_cffi

WORKDIR /app

# Copy requirements dulu (caching)
COPY requirements.txt .

# Install Python deps dari requirements
RUN pip install --no-cache-dir -r requirements.txt

# Install paket khusus untuk whisper
RUN pip install --no-cache-dir av==11.0.0
RUN pip install --no-cache-dir onnxruntime==1.15.1
RUN pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# Install tambahan untuk requests
RUN pip install --no-cache-dir beautifulsoup4 lxml

# Copy source code (TANPA cookies.txt!)
COPY . .

# Verifikasi install
RUN python --version && \
    pip --version && \
    yt-dlp --version && \
    ffmpeg -version | head -1

# Buat directory output
RUN mkdir -p /app/output

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]