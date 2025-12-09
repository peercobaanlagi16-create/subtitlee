FROM python:3.10-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential pkg-config ffmpeg git ca-certificates python3-dev gcc \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libavfilter-dev libswscale-dev libswresample-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# upgrade pip & install requirements
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# jika pip install faster-whisper di requirements gagal karena dep heavy,
# kita pastikan onnxruntime dulu, lalu install faster-whisper (no-deps) sebagai fallback:
RUN pip install --no-cache-dir onnxruntime==1.15.1 \
 && pip install --no-cache-dir --no-deps faster-whisper==1.0.0

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
