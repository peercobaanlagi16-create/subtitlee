FROM python:3.9-bullseye

RUN apt-get update && apt-get install -y \
    ffmpeg \
    pkg-config \
    python3-dev \
    build-essential \
    libavformat-dev libavcodec-dev libavdevice-dev \
    libavutil-dev libavfilter-dev libswscale-dev libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) install dependency utama
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) install faster-whisper TANPA dependencies (biar gak tarik av)
RUN pip install --no-cache-dir --no-deps "faster-whisper==0.10.0"

# 3) copy source code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
