"""P0 dashboard staging server. Must run beside the live SQLite disk; never deploy as a separate Render instance pointed at /var/data."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
BOT_ROOT = ROOT.parent / "telegram-bot" / "live"
import sys
sys.path.insert(0, str(BOT_ROOT))
from storage import Ledger

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_NAME = os.getenv("TELEGRAM_BOT_USERNAME", "").removeprefix("@")
PUBLIC_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "").rstrip("/")
DB_PATH = Path(os.getenv("DASHBOARD_DB_PATH", "/var/data/dnd-live.sqlite3"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()}
OWNER_IDS = {int(x) for x in os.getenv("DASHBOARD_OWNER_IDS", "").split(",") if x.strip().isdigit()}
SESSION_SECONDS = 8 * 3600
sessions = {}  # Development only: shared durable session store needed for multi-process deployment.
app = FastAPI(title="DND Nights admin P0", docs_url=None, redoc_url=None)

class TelegramIdentity(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str

class ScanInput(BaseModel):
    qr: str = Field(min_length=8, max_length=2048)
    request_id: str = Field(min_length=16, max_length=100)

def ledger():
    if not DB_PATH.is_file():
        raise HTTPException(503, "Existing SQLite ledger not mounted. Dashboard requires co-located access.")
    return Ledger(DB_PATH, int(os.getenv("EVENT_CAPACITY", "230")), os.getenv("EVENT_ID", "DND26"))

def require_admin(request: Request, owner=False):
    sid = request.cookies.get("dnd_session", "")
    record = sessions.get(sid)
    if not record or record["expires"] <= time.time():
        raise HTTPException(401, "Not signed in")
    uid = record["id"]
    if uid not in ADMIN_IDS or (owner and uid not in OWNER_IDS):
        raise HTTPException(403, "Not authorized")
    return uid

def check_origin(request: Request):
    if not PUBLIC_ORIGIN:
        raise HTTPException(503, "DASHBOARD_ORIGIN is required")
    if request.headers.get("origin", "").rstrip("/") != PUBLIC_ORIGIN:
        raise HTTPException(403, "Invalid request origin")

def telegram_verified(data: TelegramIdentity):
    if not BOT_TOKEN:
        raise HTTPException(503, "Telegram authentication not configured")
    values = data.model_dump(exclude_none=True)
    actual = values.pop("hash")
    check = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected) and abs(int(time.time()) - data.auth_date) <= 300

@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")

@app.get("/api/config")
def config():
    return {"bot_name": BOT_NAME, "configured": bool(BOT_NAME and PUBLIC_ORIGIN)}

@app.post("/api/auth/telegram")
async def login(data: TelegramIdentity, request: Request, response: Response):
    check_origin(request)
    if not telegram_verified(data) or data.id not in ADMIN_IDS:
        raise HTTPException(403, "Unauthorized Telegram account")
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = {"id": data.id, "expires": time.time() + SESSION_SECONDS, "name": data.first_name or "Admin"}
    response.set_cookie("dnd_session", session_id, httponly=True, secure=True, samesite="strict", max_age=SESSION_SECONDS, path="/")
    return {"ok": True}

@app.post("/api/logout")
def logout(request: Request, response: Response):
    check_origin(request)
    sessions.pop(request.cookies.get("dnd_session", ""), None)
    response.delete_cookie("dnd_session", path="/")
    return {"ok": True}

@app.get("/api/me")
def me(request: Request):
    uid = require_admin(request)
    record = sessions[request.cookies["dnd_session"]]
    return {"id": uid, "name": record["name"], "role": "owner" if uid in OWNER_IDS else "admin"}

@app.get("/api/overview")
def overview(request: Request):
    require_admin(request)
    l = ledger()
    with l.db() as db:
        summary = db.execute("""
          SELECT COALESCE(SUM(CASE WHEN status='paid' THEN quantity ELSE 0 END),0) AS paid_tickets,
                 COALESCE(SUM(CASE WHEN status='paid' THEN total_cents ELSE 0 END),0) AS revenue_cents,
                 COUNT(CASE WHEN status IN ('review','review_late') THEN 1 END) AS pending_review,
                 COUNT(*) AS total_orders FROM orders
        """).fetchone()
        checkins = db.execute("""SELECT COUNT(*) FROM tickets t JOIN orders o USING(serial)
                                  WHERE o.status='paid' AND t.used_at IS NOT NULL""").fetchone()[0]
        activity = [dict(x) for x in db.execute(
            "SELECT action,serial,actor,created_at FROM audit ORDER BY id DESC LIMIT 8")]
    campaign = l.campaign()
    return {**dict(summary), "checkins": checkins, "capacity": l.capacity,
            "campaign": campaign, "activity": activity}

@app.get("/api/orders")
def orders(request: Request, status: str = "", q: str = ""):
    require_admin(request)
    if len(q) > 100:
        raise HTTPException(400, "Search too long")
    l = ledger()
    with l.db() as db:
        rows = db.execute("""SELECT serial,user_id,details,quantity,total_cents,status,created_at,expires_at
                             FROM orders ORDER BY created_at DESC LIMIT 2000""").fetchall()
    out = []
    for item in rows:
        r = dict(item)
        details = json.loads(r.pop("details"))
        r["name"] = details.get("name", "")
        r["payer_name"] = details.get("payer_name", r["name"])
        r["promoter_code"] = details.get("promoter_code", "")
        if status and r["status"] != status:
            continue
        if q and q.casefold() not in " ".join(str(v) for v in r.values()).casefold():
            continue
        out.append(r)
        if len(out) >= 200:
            break
    return {"orders": out}

def parse_qr(raw):
    """Accept raw secret token or the live bot's t.me start=check_TOKEN link."""
    from urllib.parse import parse_qs
    parsed = urlparse(raw)
    if parsed.scheme:
        if parsed.scheme != "https" or parsed.hostname not in ("t.me", "telegram.me"):
            raise HTTPException(400, "Unsupported QR link")
        start = parse_qs(parsed.query).get("start", [""])[0]
        raw = start
    raw = raw.removeprefix("check_").removeprefix("DND:")
    if len(raw) > 200 or not raw or not all(c.isalnum() or c in "-_" for c in raw):
        raise HTTPException(400, "Invalid QR token")
    return raw

@app.post("/api/checkin")
def checkin(payload: ScanInput, request: Request):
    uid = require_admin(request)
    check_origin(request)
    token = parse_qr(payload.qr.strip())
    # Reuse the ledger's existing transactionally safe, idempotent door admission.
    result = ledger().door_admit(payload.request_id, token, uid, time.time())
    return result
