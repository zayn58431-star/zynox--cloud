# zynox_server1.py
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3, uuid, datetime, os, json
from cryptography.fernet import Fernet

# ----------------------------
# Config
# ----------------------------
API_KEY = os.environ.get("ZYNX_API_KEY", "test-demo-key")
DB_FILE = "zynox_cloud.db"
KEY_FILE = "secret.key"

app = FastAPI(title="Zynox Cloud Memory (Prototype)")

# Health check route
@app.get("/ping")
def ping():
    return {"status": "ok", "message": "Zynox Cloud is alive "}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can restrict to your frontend domain later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Load Encryption Key
# ----------------------------
def load_key():
    if not os.path.exists(KEY_FILE):
        raise RuntimeError("❌ secret.key not found. Run generate_key.py first!")
    with open(KEY_FILE, "rb") as f:
        return f.read()

fernet = Fernet(load_key())

# ----------------------------
# Database Setup
# ----------------------------
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

# ----------------------------
# Request Models
# ----------------------------
class UploadRequest(BaseModel):
    owner_id: str
    key: str | None = None
    tags: list[str] | None = None
    data: str  # 🔑 plain text data (will be encrypted)

# ----------------------------
# API Key Check
# ----------------------------
def check_api_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ----------------------------
# Emotion Detection (Simple)
# ----------------------------
def detect_emotion(text: str) -> str | None:
    text = text.lower()
    if any(w in text for w in ["sad", "depressed", "tired", "lonely"]):
        return "sad"
    if any(w in text for w in ["happy", "joy", "excited", "great"]):
        return "happy"
    if any(w in text for w in ["angry", "mad", "furious", "upset"]):
        return "angry"
    return None

# ----------------------------
# Routes
# ----------------------------
@app.get("/", response_class=HTMLResponse)
def landing_page():
    return """
    <html>
        <head><title>Zynox Cloud Storage</title></head>
        <body style="font-family: Arial; background-color:#f4f4f4; text-align:center; padding:50px;">
            <h1 style="color:#2E86C1;"> Zynox Cloud Storage</h1>
            <p>This is the prototype cloud-based memory system built only for <b>Zynox AGI</b>.</p>
            <h3>Features so far:</h3>
            <ul style="text-align:left; display:inline-block;">
                <li>Secure <b>memory storage</b> using AES (Fernet) encryption</li>
                <li>SQLite database with memory versioning</li>
                <li>API endpoints (<code>/v1/save</code>, <code>/v1/list</code>, <code>/v1/download</code>, <code>/v1/delete</code>, <code>/v1/query</code>)</li>
                <li>Auto-tagging of emotions (happy/sad/angry) based on memory text</li>
                <li>Protected with API Key system</li>
                <li>Works inside virtual environment (<b>.venv</b>)</li>
            </ul>
            <p>Explore full API docs 👉 <a href='/docs'>Swagger UI</a></p>
        </body>
    </html>
    """

@app.post("/v1/save")
def save_memory(payload: UploadRequest, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    mem_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # 🔑 Encrypt before saving
    encrypted = fernet.encrypt(payload.data.encode()).decode()

    # ✅ Auto emotion tagging
    tags = payload.tags or []
    emotion = detect_emotion(payload.data)
    if emotion and emotion not in tags:
        tags.append(emotion)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memories (id, owner_id, key, tags, created_at, updated_at, enc_blob, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (mem_id, payload.owner_id, payload.key or "", json.dumps(tags), now, now, encrypted, 1)
    )
    conn.commit()
    conn.close()
    return {"status":"ok", "id": mem_id, "tags": tags}

@app.get("/v1/list/{owner_id}")
def list_memories(owner_id: str, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, key, tags, created_at, updated_at, version FROM memories WHERE owner_id = ?", (owner_id,))
    rows = c.fetchall()
    conn.close()
    items = []
    for r in rows:
        items.append({
            "id":r[0],
            "key": r[1],
            "tags": json.loads(r[2]) if r[2] else [],
            "created_at":r[3],
            "updated_at":r[4],
            "version": r[5]
        })
    return {"status":"ok", "items": items}

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

    # 🔑 Decrypt before returning
    decrypted = fernet.decrypt(row[0].encode()).decode()
    return {"status":"ok", "data": decrypted}

@app.delete("/v1/delete/{mem_id}")
def delete(mem_id: str, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
    conn.commit()
    conn.close()
    return {"status":"ok", "deleted": mem_id}
    
@app.post("/v1/query/{owner_id}")
def query_memories(owner_id: str, body: dict, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    emotion = body.get("emotion")
    keyword = body.get("keyword")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, key, tags, created_at, enc_blob FROM memories WHERE owner_id = ?", (owner_id,))
    rows = c.fetchall()
    conn.close()

    results = []
    for r in rows:
        try:
            decrypted = fernet.decrypt(r[4].encode()).decode()
        except:
            continue
        tags = json.loads(r[2]) if r[2] else []

        # match by emotion tag or keyword
        if (emotion and emotion in tags) or (keyword and keyword.lower() in decrypted.lower()):
            results.append({
                "id": r[0],
                "key": r[1],
                "tags": tags,
                "created_at": r[3],
                "text": decrypted
            })

    return {"status": "ok", "results": results}
