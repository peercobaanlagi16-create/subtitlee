# auth_api.py (FastAPI Version - COMPLETE)

import os
import requests
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ============================================
# Load environment variables
# ============================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")  # wajib ditambahkan di .env backend

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY in environment")

GOTRUE_BASE = f"{SUPABASE_URL}/auth/v1"


# ============================================
# MODELS
# ============================================
class LoginInput(BaseModel):
    email: str
    password: str


class SignupInput(BaseModel):
    email: str
    password: str


# ============================================
# HELPERS
# ============================================
def std_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }


# ============================================
# SIGNUP (CREATE USER)
# ============================================
@router.post("/api/auth/signup")
def signup(payload: SignupInput):
    """
    Membuat user baru di Supabase
    Body: { email, password }
    """

    url = f"{GOTRUE_BASE}/signup"

    r = requests.post(
        url,
        headers=std_headers(),
        json={
            "email": payload.email,
            "password": payload.password
        }
    )

    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=r.text)

    return r.json()


# ============================================
# LOGIN
# ============================================
@router.post("/api/auth/login")
def login(payload: LoginInput):
    """
    Login Supabase menggunakan email + password
    Return: access_token, refresh_token, token_type, user, dll.
    """

    url = f"{GOTRUE_BASE}/token?grant_type=password"

    r = requests.post(
        url,
        headers=std_headers(),
        json={
            "email": payload.email,
            "password": payload.password
        }
    )

    if r.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return r.json()


# ============================================
# USER FROM TOKEN
# ============================================
@router.get("/api/auth/user")
def get_user(request: Request):
    """
    Ambil user dari access_token
    Header: Authorization: Bearer <token>
    """

    auth = request.headers.get("authorization")

    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth.split(" ", 1)[1]

    r = requests.get(
        f"{GOTRUE_BASE}/user",
        headers={
            **std_headers(),
            "Authorization": f"Bearer {token}"
        }
    )

    if r.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid token")

    return r.json()
