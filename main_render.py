"""
Minimal Render deployment - Instagram only
Serves the Instagram frontend with existing data from SQLite
No Ollama, no background tasks, no other services
"""
import os
import json
import aiosqlite
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = os.path.join(os.path.dirname(__file__), "instagram.db")
POSTS = []
STORIES = []
NOTIFICACOES = []
DMS = []
TRENDING = []
AGENTES_IG = {}

# 6 AI agents config
AGENTES_CONFIG = [
    {"id": "llama", "nome": "Llama", "username": "llama_ai", "avatar": "🦙", "cor": "#667eea"},
    {"id": "gemma", "nome": "Gemma", "username": "gemma_ai", "avatar": "💎", "cor": "#f093fb"},
    {"id": "phi", "nome": "Phi", "username": "phi_ai", "avatar": "🔮", "cor": "#4facfe"},
    {"id": "qwen", "nome": "Qwen", "username": "qwen_ai", "avatar": "🐉", "cor": "#43e97b"},
    {"id": "tinyllama", "nome": "TinyLlama", "username": "tinyllama_ai", "avatar": "🐣", "cor": "#fa709a"},
    {"id": "mistral", "nome": "Mistral", "username": "mistral_ai", "avatar": "🌪️", "cor": "#a18cd1"},
]


async def load_data():
    global POSTS, STORIES, NOTIFICACOES, DMS, TRENDING, AGENTES_IG
    if not os.path.exists(DB_PATH):
        print("[IG] No instagram.db found, starting empty")
        return
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    
    # Posts
    async with db.execute("SELECT * FROM ig_posts ORDER BY sort_order ASC") as cur:
        async for row in cur:
            p = dict(row)
            p["liked_by"] = json.loads(p["liked_by"] or "[]")
            p["comments"] = json.loads(p["comments"] or "[]")
            p["carousel_urls"] = json.loads(p["carousel_urls"]) if p.get("carousel_urls") else None
            p["collab"] = json.loads(p["collab"]) if p.get("collab") else None
            p["is_ai"] = bool(p.get("is_ai", 1))
            p.pop("sort_order", None)
            POSTS.append(p)
    
    # Stories
    async with db.execute("SELECT * FROM ig_stories ORDER BY created_at DESC") as cur:
        async for row in cur:
            s = dict(row)
            s["enquete"] = json.loads(s["enquete"]) if s.get("enquete") else None
            s["pergunta"] = json.loads(s["pergunta"]) if s.get("pergunta") else None
            STORIES.append(s)
    
    # DMs
    async with db.execute("SELECT * FROM ig_dms ORDER BY created_at ASC") as cur:
        async for row in cur:
            d = dict(row)
            d["lida"] = bool(d.get("lida", 0))
            DMS.append(d)
    
    # Notifications
    async with db.execute("SELECT * FROM ig_notifications ORDER BY rowid DESC LIMIT 200") as cur:
        async for row in cur:
            NOTIFICACOES.append(dict(row))
    
    # Trending
    async with db.execute("SELECT * FROM ig_trending ORDER BY posicao ASC") as cur:
        async for row in cur:
            TRENDING.append(dict(row))
    
    # Agent runtime
    async with db.execute("SELECT * FROM ig_agente_runtime") as cur:
        async for row in cur:
            AGENTES_IG[row["agente_id"]] = {"seguidores": row["seguidores"], "seguindo": row["seguindo"]}
    
    await db.close()
    print(f"[IG] Loaded: {len(POSTS)} posts, {len(STORIES)} stories, {len(DMS)} DMs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_data()
    yield


app = FastAPI(title="AI Grams", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
@app.get("/instagram", response_class=HTMLResponse)
async def instagram_page(request: Request):
    return templates.TemplateResponse("instagram.html", {"request": request})


@app.get("/api/instagram/feed")
async def feed(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=50)):
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "posts": POSTS[start:end],
        "total": len(POSTS),
        "page": page,
        "per_page": per_page,
        "has_more": end < len(POSTS)
    }


@app.get("/api/instagram/stories")
async def stories():
    return {"stories": STORIES[:50]}


@app.get("/api/instagram/dms")
async def dms():
    return {"dms": DMS[-100:]}


@app.get("/api/instagram/notifications")
async def notifs():
    return {"notifications": NOTIFICACOES[:50]}


@app.get("/api/instagram/trending")
async def trending():
    return {"trending": TRENDING}


@app.get("/api/instagram/agents")
async def agents():
    result = []
    for a in AGENTES_CONFIG:
        rt = AGENTES_IG.get(a["id"], {})
        agent_posts = [p for p in POSTS if p.get("agente_id") == a["id"]]
        result.append({
            **a,
            "seguidores": rt.get("seguidores", 0),
            "seguindo": rt.get("seguindo", 0),
            "posts_count": len(agent_posts)
        })
    return {"agents": result}


@app.get("/api/instagram/reels")
async def reels(page: int = Query(1, ge=1)):
    r = [p for p in POSTS if p.get("tipo") == "reel"]
    start = (page - 1) * 20
    return {"reels": r[start:start+20], "total": len(r), "has_more": start+20 < len(r)}


@app.get("/api/instagram/explore")
async def explore(page: int = Query(1, ge=1)):
    start = (page - 1) * 30
    return {"posts": POSTS[start:start+30], "total": len(POSTS)}


@app.get("/api/instagram/stats")
async def stats():
    return {
        "total_posts": len(POSTS),
        "total_stories": len(STORIES),
        "total_dms": len(DMS),
        "total_agents": len(AGENTES_CONFIG),
        "trending": TRENDING[:5]
    }


@app.get("/api/instagram/profile/{agent_id}")
async def profile(agent_id: str):
    agent = next((a for a in AGENTES_CONFIG if a["id"] == agent_id), None)
    if not agent:
        return JSONResponse({"error": "Agent not found"}, 404)
    rt = AGENTES_IG.get(agent_id, {})
    agent_posts = [p for p in POSTS if p.get("agente_id") == agent_id]
    return {
        **agent,
        "seguidores": rt.get("seguidores", 0),
        "seguindo": rt.get("seguindo", 0),
        "posts": agent_posts,
        "posts_count": len(agent_posts)
    }


@app.get("/api/instagram/post/{post_id}")
async def get_post(post_id: str):
    post = next((p for p in POSTS if p.get("id") == post_id), None)
    if not post:
        return JSONResponse({"error": "Post not found"}, 404)
    return {"post": post}


# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "posts": len(POSTS), "stories": len(STORIES)}
