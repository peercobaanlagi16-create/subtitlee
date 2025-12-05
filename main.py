from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess, os, uuid, json, sys, threading, time  # ← tambah threading & time

APP_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(APP_DIR, "output")
os.makedirs(DATA_DIR, exist_ok=True)

PYTHON = sys.executable

app = FastAPI(title="Video Subtitle Translator Backend")

# Auth (tidak diubah)
try:
    from auth_api import router as auth_router
    app.include_router(auth_router)
    print("Auth router loaded!")
except Exception as e:
    print("AUTH ROUTER ERROR:", e)

# ======================================
# CORS
# ======================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ======================================
# Helper
# ======================================
def update_status(job_id, status, log=""):
    job_dir = os.path.join(DATA_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    status_file = os.path.join(job_dir, "status.json")

    data = {"status": status, "log": log}
    if status == "done":
        data["output"] = f"/api/output/{job_id}"

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ======================================
# Worker — VERSI YANG PASTI JALAN 100%
# ======================================
def run_worker_async(job_id, filepath, target, size, is_url):
    worker = os.path.join(APP_DIR, "worker.py")
    log_file = os.path.join(DATA_DIR, job_id, "worker.log")

    cmd = [
        PYTHON, worker,
        job_id, filepath, target, str(int(is_url)), str(size)
    ]

    def start_worker():
        # Buat log langsung dari detik pertama
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"[WORKER STARTED] {time.strftime('%H:%M:%S')}\n")
            f.write(f"COMMAND: {' '.join(cmd)}\n\n")
            f.flush()

            subprocess.Popen(
                cmd,
                stdout=f,
                stderr=f,
                cwd=APP_DIR,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

    # Jalankan di thread terpisah — PASTI jalan!
    thread = threading.Thread(target=start_worker, daemon=True)
    thread.start()


# ======================================
# UPLOAD VIDEO
# ======================================
@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(...),
    target: str = Form("id"),
    size: int = Form(26)
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

    # LANGSUNG JALANKAN WORKER (bukan lewat BackgroundTasks)
    run_worker_async(job_id, filepath, target, size, False)

    return {"job_id": job_id}


# ======================================
# START FROM URL
# ======================================
@app.post("/api/start")
async def start_url(
    embed: str = Form(...),
    target: str = Form("id"),
    size: int = Form(26)
):
    if not embed.strip():
        raise HTTPException(400, "URL kosong")

    job_id = str(uuid.uuid4())
    update_status(job_id, "queued", "URL diterima")

    # LANGSUNG JALANKAN WORKER
    run_worker_async(job_id, embed, target, size, True)

    return {"job_id": job_id}


# ======================================
# CHECK STATUS
# ======================================
@app.get("/api/status/{job_id}")
async def check_status(job_id: str):
    status_file = os.path.join(DATA_DIR, job_id, "status.json")

    if not os.path.exists(status_file):
        return {"status": "queued", "log": "Menunggu..."}

    try:
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"status": "error", "log": "Status corrupt"}


# ======================================
# DOWNLOAD
# ======================================
@app.get("/api/output/{job_id}")
async def download_result(job_id: str):
    output_path = os.path.join(DATA_DIR, job_id, "output.mp4")

    if not os.path.exists(output_path):
        raise HTTPException(404, "Belum selesai")

    filename = f"{job_id.replace('-', '')}_subtitle.mp4"

    return FileResponse(
        output_path, media_type="video/mp4", filename=filename
    )


# ======================================
# ROOT
# ======================================
@app.get("/")
async def root():
    return HTMLResponse("<h3>Backend Online</h3>")