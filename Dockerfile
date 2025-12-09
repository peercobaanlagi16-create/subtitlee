# Dockerfile (with deno + media deps)
FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Sistem deps (ffmpeg + build deps + libav dev libs + pkg-config + curl)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential pkg-config ffmpeg \
    python3 python3-dev python3-pip python3-venv gcc \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libavfilter-dev libswscale-dev libswresample-dev \
 && rm -rf /var/lib/apt/lists/*

# buat symlink python/pip (memastikan 'python' dan 'pip' tersedia)
RUN ln -s /usr/bin/python3 /usr/local/bin/python \
 && ln -s /usr/bin/pip3 /usr/local/bin/pip

WORKDIR /app

# copy hanya requirements dulu (cache)
COPY requirements.txt .

# upgrade pip & tools lalu install requirements (tanpa paksa av)
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# coba pasang av dari wheel/source (jika sistem libs cocok). Jika gagal, lanjut (|| true)
# (ini tidak memblok build jika av build gagal)
RUN pip install --no-cache-dir av==11.0.0 || true

# pastikan onnxruntime dan faster-whisper (no-deps) terpasang sebagai fallback
RUN pip install --no-cache-dir onnxruntime==1.15.1 \
 && pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# ---- INSTAL DENO (untuk yt-dlp EJS support) ----
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
 && curl -fsSL https://deno.land/x/install/install.sh | sh \
 && ln -s /root/.deno/bin/deno /usr/local/bin/deno \
 && deno --version

# copy seluruh source
COPY . .

# buat folder output (pastikan permission)
RUN mkdir -p /app/output && chmod 777 /app/output

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
