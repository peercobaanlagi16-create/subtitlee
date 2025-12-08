from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess, os, uuid, json, sys, time  # ← cukup pakai time, tidak butuh threading

APP_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(APP_DIR, "output")
os.makedirs(DATA_DIR, exist_ok=True)

PYTHON = sys.executable

app = FastAPI(title="Video Subtitle Translator Backend")

# ==========================
# Auth router
# ==========================
try:
    from auth_api import router as auth_router
    app.include_router(auth_router)
    print("Auth router loaded!")
except Exception as e:
    print("AUTH ROUTER ERROR:", e)

# ==========================
# CORS
# ==========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ==========================
# Helper status
# ==========================
def update_status(job_id, status, log=""):
    job_dir = os.path.join(DATA_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    status_file = os.path.join(job_dir, "status.json")

    data = {"status": status, "log": log}
    if status == "done":
        data["output"] = f"/api/output/{job_id}"

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==========================
# Jalankan worker (simple)
# ==========================
def run_worker(job_id: str, src: str, target: str, size: int, is_url: bool):
    """
    Start worker.py sebagai proses terpisah.
    Kalau gagal start → status job jadi 'failed'.
    """
    worker_path = os.path.join(APP_DIR, "worker.py")
    job_dir = os.path.join(DATA_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    log_file = os.path.join(job_dir, "worker_start.log")

    cmd = [
        PYTHON,
        worker_path,
        job_id,
        src,
        target,
        str(int(is_url)),
        str(size),
    ]

    try:
        # log perintah yang dijalankan
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] START WORKER\n")
            f.write("CMD: " + " ".join(cmd) + "\n")

        # jalankan worker di background
        subprocess.Popen(
            cmd,
            cwd=APP_DIR,
        )

    except Exception as e:
        # kalau gagal spawn, tandai job error
        update_status(job_id, "failed", f"Worker start error: {e}")
        raise

# ==========================
# /api/upload : upload file
# ==========================
@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(...),
    target: str = Form("id"),
    size: int = Form(26),
):
    if not file.filename:
        raise HTTPException(400, "No file uploaded")

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(DATA_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    filepath = os.path.join(job_dir, file.filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    update_status(job_id, "queued", "File uploaded")

    # Start worker dengan file lokal
    run_worker(job_id, filepath, target, size, is_url=False)

    return {"job_id": job_id}

# ==========================
# /api/start : dari URL
# ==========================
@app.post("/api/start")
async def start_url(
    embed: str = Form(...),
    target: str = Form("id"),
    size: int = Form(26),
):
    if not embed.strip():
        raise HTTPException(400, "URL kosong")

    job_id = str(uuid.uuid4())
    update_status(job_id, "queued", "URL diterima")

    # Start worker dengan URL
    run_worker(job_id, embed, target, size, is_url=True)

    return {"job_id": job_id}

# ==========================
# /api/status/{job_id}
# ==========================
@app.get("/api/status/{job_id}")
async def check_status(job_id: str):
    status_file = os.path.join(DATA_DIR, job_id, "status.json")
    if not os.path.exists(status_file):
        return {"status": "queued", "log": "Menunggu..."}

    try:
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "error", "log": "Status corrupt"}

# ==========================
# /api/output/{job_id}
# ==========================
@app.get("/api/output/{job_id}")
async def download_result(job_id: str):
    output_path = os.path.join(DATA_DIR, job_id, "output.mp4")

    if not os.path.exists(output_path):
        raise HTTPException(404, "Belum selesai")

    filename = f"{job_id.replace('-', '')}_subtitle.mp4"
    return FileResponse(output_path, media_type="video/mp4", filename=filename)

# ==========================
# Root
# ==========================
@app.get("/")
async def root():
    return HTMLResponse("<h3>Backend Online</h3>")
