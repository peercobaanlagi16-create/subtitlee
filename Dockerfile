# Dockerfile — gunakan python3-av dari apt untuk menghindari build PyAV via pip
FROM python:3.10-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential pkg-config ffmpeg git ca-certificates python3-dev gcc \
    python3-av \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libavfilter-dev libswscale-dev libswresample-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# COPY only requirements first for caching
COPY requirements.txt .

# upgrade pip & install requirements (pastikan 'av' TIDAK ada di requirements.txt)
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Pastikan onnxruntime + faster-whisper tersedia.
# faster-whisper mengimpor 'av' di runtime; karena kita sudah install python3-av di apt,
# faster-whisper tidak lagi memicu build av dari pip.
RUN pip install --no-cache-dir onnxruntime==1.15.1 \
 && pip install --no-cache-dir --no-deps faster-whisper==1.0.0

# Copy aplikasi
COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
