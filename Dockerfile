FROM python:3.10-bullseye

# Install system dependencies required for PyAV, Faster-Whisper & FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    pkg-config \
    python3-dev \
    build-essential \
    libavformat-dev libavcodec-dev libavdevice-dev \
    libavutil-dev libavfilter-dev libswscale-dev libswresample-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port (optional, Koyeb detects automatically)
EXPOSE 8000

# Start FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
