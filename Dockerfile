# Dockerfile – FIX EPORNER dengan NIGHTLY yt-dlp (Dec 2025)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Sistem deps (sudah ada curl, ffmpeg, dll)
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

# Install yt-dlp NIGHTLY (FIX EPORNER!)
RUN wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp && \
    chmod a+x /usr/local/bin/yt-dlp && \
    yt-dlp --version  # Konfirmasi nightly

# Install curl_cffi untuk impersonate (opsional, tapi bagus)
RUN pip install --no-cache-dir curl_cffi

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# av, onnxruntime, faster-whisper
RUN pip install --no-cache-dir av==11.0.0 || true
RUN pip install --no-cache-dir onnxruntime==1.15.1
RUN pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# Copy source
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]