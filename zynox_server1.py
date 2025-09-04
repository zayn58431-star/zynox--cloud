# zynox_server1.py  (cloud-ready)
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3, uuid, datetime, os, json
from cryptography.fernet import Fernet

API_KEY = os.environ.get("ZYNX_API_KEY", "test-demo-key")
DB_FILE = "zynox_cloud.db"
KEY_FILE = "secret.key"

app = FastAPI(title="Zynox Cloud Memory (Prototype)")

# ---- Key management: prefer env var, fallback to file, else generate ----
def load_key() -> bytes:
    k = os.environ.get("FERNET_KEY")
    if k:
        return k.encode()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    # last resort: generate one (note: old data becomes unreadable after redeploy)
    new_k = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(new_k)
    return new_k

fernet = Fernet(load_key())

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        key TEXT,
        tags TEXT,
        created_at TEXT,
        updated_at TEXT,
        enc_blob TEXT,
        version INTEGER DEFAULT 1
    )
    """)
    conn.commit()
    conn.close()

init_db()

class UploadRequest(BaseModel):
    owner_id: str
    key: str | None = None
    tags: list[str] | None = None
    data: str  # plain text; will be encrypted

def check_api_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.get("/", response_class=HTMLResponse)
def landing_page():
    return """
    <html>
      <head><title>Zynox Cloud Storage</title></head>
      <body style="font-family:Arial;background:#f6f8fb;text-align:center;padding:48px">
        <h1>🚀 Zynox Cloud Storage</h1>
        <p>Prototype encrypted memory service for <b>Zynox AGI</b>.</p>
        <p>Open <a href="/docs">/docs</a> to try the API.</p>
      </body>
    </html>
    """

@app.post("/v1/save")
def save_memory(payload: UploadRequest, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    mem_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat() + "Z"
    enc = fernet.encrypt(payload.data.encode()).decode()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memories (id, owner_id, key, tags, created_at, updated_at, enc_blob, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (mem_id, payload.owner_id, payload.key or "", json.dumps(payload.tags or []), now, now, enc, 1)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "id": mem_id}

@app.get("/v1/list/{owner_id}")
def list_memories(owner_id: str, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, key, tags, created_at, updated_at, version FROM memories WHERE owner_id = ?", (owner_id,))
    rows = c.fetchall()
    conn.close()
    return {
        "status": "ok",
        "items": [
            {"id": r[0], "key": r[1], "tags": json.loads(r[2]) if r[2] else [], "created_at": r[3], "updated_at": r[4], "version": r[5]}
            for r in rows
        ],
    }

@app.get("/v1/download/{mem_id}")
def download(mem_id: str, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT enc_blob FROM memories WHERE id = ?", (mem_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    plain = fernet.decrypt(row[0].encode()).decode()
    return {"status": "ok", "data": plain}

@app.delete("/v1/delete/{mem_id}")
def delete(mem_id: str, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
    conn.commit()
    conn.close()
    return {"status": "ok", "deleted": mem_id}
