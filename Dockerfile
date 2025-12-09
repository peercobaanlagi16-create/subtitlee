# Dockerfile — gunakan Python 3.10 (mendukung sintaks union type `|`)
FROM python:3.10-slim-bullseye

# Jaga agar Python tidak buat pyc dan flush output langsung
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install paket sistem yang diperlukan untuk ffmpeg / PyAV / build wheels
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    ffmpeg \
    git \
    ca-certificates \
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

WORKDIR /app

# Copy file requirements dan upgrade pip/setuptools/wheel sebelum install
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Jika kamu ingin menginstall faster-whisper tanpa dependencies (opsional)
# sehingga pip tidak coba compile/ambil av lagi, uncomment baris berikut
# RUN pip install --no-cache-dir --no-deps "faster-whisper==0.10.0"

# Copy seluruh source app
COPY . .

# Expose port uvicorn default
EXPOSE 8000

# Start command (sesuaikan jika entrypoint/main file berbeda)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
