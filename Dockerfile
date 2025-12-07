FROM python:3.10-slim

# Install ffmpeg and libav* dev libraries for python-av / faster-whisper
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavformat-dev libavcodec-dev libavdevice-dev \
    libavutil-dev libavfilter-dev libswscale-dev libswresample-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# (env tetap di-set dari Koyeb, tidak wajib di sini)
# ENV FFMPEG=ffmpeg
# ENV DATA_DIR=./output

# Start FastAPI with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
