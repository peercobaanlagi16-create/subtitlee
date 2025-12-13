# Dockerfile — FINAL & AMAN 100% (NO cookies.txt di repo!)
FROM ubuntu:22.04

ENV OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1


ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Install deps sistem
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget git build-essential pkg-config ffmpeg \
        python3 python3-pip python3-dev gcc g++ \
        libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
        libavfilter-dev libswscale-dev libswresample-dev \
        libssl-dev libffi-dev libxml2-dev libxslt-dev zlib1g-dev \
        # Tambahan untuk networking dan tools
        iproute2 net-tools dnsutils telnet \
        # Untuk video processing
        libsm6 libxext6 libxrender-dev libgl1-mesa-glx \
        # Cleanup
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Python symlink dan upgrade pip
RUN ln -s /usr/bin/python3 /usr/local/bin/python && \
    ln -s /usr/bin/pip3 /usr/local/bin/pip && \
    pip install --upgrade --no-cache-dir pip setuptools wheel

# Install yt-dlp TERBARU dari master branch
RUN pip install --upgrade --no-cache-dir git+https://github.com/yt-dlp/yt-dlp.git@master

# Install curl_cffi untuk impersonate Chrome modern
RUN pip install --no-cache-dir curl_cffi==0.7.2

WORKDIR /app

# Copy requirements dulu (caching)
COPY requirements.txt .

# Install Python deps dari requirements
RUN pip install --no-cache-dir -r requirements.txt

# Install paket khusus untuk whisper dan scraping
RUN pip install --no-cache-dir \
    av==11.0.0 \
    beautifulsoup4==4.12.3 \
    lxml==5.3.0 \
    fake-useragent==1.5.0 \
    cloudscraper==1.2.71 \
    selenium-wire==5.1.0 \
    undetected-chromedriver==3.5.5

# Install faster-whisper (terpisah karena dependencies khusus)
RUN pip install --no-cache-dir --no-deps faster-whisper==1.0.3 && \
    pip install --no-cache-dir ctranslate2==4.4.0
RUN pip install --no-cache-dir tokenizers==0.15.2

# Verifikasi install
RUN python --version && \
    pip --version && \
    yt-dlp --version && \
    ffmpeg -version | head -1 && \
    curl --version | head -1

# Copy source code
COPY . .

# Buat directory output dengan permissions
RUN mkdir -p /app/output && \
    chmod -R 755 /app/output

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

EXPOSE 8000

# Command dengan gunicorn untuk production (lebih stable)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "300"]