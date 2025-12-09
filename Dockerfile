# Dockerfile (rekomendasi)
FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Sistem deps (ffmpeg + build deps + libav dev libs + pkg-config)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential pkg-config ffmpeg \
    python3 python3-dev python3-pip python3-venv gcc \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libavfilter-dev libswscale-dev libswresample-dev \
 && rm -rf /var/lib/apt/lists/*

# gunakan python3 pip yang ada
RUN ln -s /usr/bin/python3 /usr/local/bin/python \
 && ln -s /usr/bin/pip3 /usr/local/bin/pip

WORKDIR /app

# Copy only requirements first (caching)
COPY requirements.txt .

RUN apt-get update && apt-get install -y curl \
 && curl -fsSL https://deno.land/x/install/install.sh | sh \
 && ln -s /root/.deno/bin/deno /usr/local/bin/deno \
 && deno --version

# Upgrade pip & install basic wheel tools
RUN pip install --upgrade pip setuptools wheel

# Install requirements but DO NOT include `av` in requirements.txt
# (we'll try to install av explicitly after system libs are available)
RUN pip install --no-cache-dir -r requirements.txt

# OPTIONAL: try to install av now (should use system libs via pkg-config)
# If this fails in your environment, comment out the line below.
RUN pip install --no-cache-dir av==11.0.0 || true

# Install onnxruntime and faster-whisper as fallback (no-deps)
# faster-whisper may still import av at runtime; installing no-deps avoids pip building av
RUN pip install --no-cache-dir onnxruntime==1.15.1 \
 && pip install --no-cache-dir --no-deps faster-whisper==1.0.0

 
# Copy app source
COPY . .

EXPOSE 8000

# command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
