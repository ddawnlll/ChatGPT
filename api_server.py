from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from uvicorn import run

from wrapper import ChatGPT


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "chats.sqlite3"
SESSION_STORE: dict[str, dict[str, Any]] = {}
CHAT_STORE: dict[str, dict[str, Any]] = {}
CHAT_CLIENTS: dict[str, ChatGPT] = {}
ALLOWED_THINKING_MODES = {"instant", "extended", "pro"}


class CookieItem(BaseModel):
    name: str
    value: str
    domain: str | None = None
    path: str | None = None
    expires: str | None = None
    httpOnly: bool | None = None
    secure: bool | None = None
    sameSite: str | None = None


class SessionMaterialRequest(BaseModel):
    proxy: str | None = None
    session_id: str | None = None
    cookies: str | list[CookieItem] | dict[str, str] | None = None
    authorization: str | None = None
    thinking_mode: str | None = None
    model_name: str | None = None


class ConversationRequest(SessionMaterialRequest):
    message: str
    image: str | None = None


class CreateChatRequest(SessionMaterialRequest):
    title: str | None = None


class SendMessageRequest(BaseModel):
    message: str
    image: str | None = None


class RenameChatRequest(BaseModel):
    title: str


class ChatSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ChatDetail(ChatSummary):
    messages: list[dict[str, Any]]
    session_id: str | None = None
    thinking_mode: str
    model_name: str


class MessageRecord(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    image: bool = False



def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()



def db_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection



def init_db() -> None:
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT,
                thinking_mode TEXT NOT NULL,
                model_name TEXT NOT NULL,
                session_material_json TEXT NOT NULL,
                remote_conversation_started INTEGER NOT NULL DEFAULT 0,
                remote_conversation_id TEXT,
                remote_parent_message_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                image INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()



def clear_persistent_storage() -> None:
    with db_connection() as conn:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM chats")
        conn.commit()



def normalize_thinking_mode(thinking_mode: str | None) -> str:
    normalized = (thinking_mode or "instant").strip().lower()
    if normalized not in ALLOWED_THINKING_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid thinking mode: {thinking_mode}")
    return normalized



def normalize_model_name(model_name: str | None) -> str:
    normalized = (model_name or "auto").strip()
    return normalized or "auto"



def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for cookie_part in cookie_header.split(";"):
        if "=" not in cookie_part:
            continue
        name, value = cookie_part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value
    return cookies



def normalize_cookies(cookies: Any) -> dict[str, str] | None:
    if cookies is None:
        return None

    if isinstance(cookies, str):
        parsed = parse_cookie_header(cookies)
        return parsed or None

    if isinstance(cookies, dict):
        if not cookies:
            return None
        if all(isinstance(key, str) and isinstance(value, str) for key, value in cookies.items()):
            return cookies
        raise HTTPException(status_code=400, detail="Invalid cookies payload")

    if isinstance(cookies, list):
        normalized: dict[str, str] = {}
        for cookie in cookies:
            if isinstance(cookie, CookieItem):
                normalized[cookie.name] = cookie.value
            elif isinstance(cookie, dict) and cookie.get("name") is not None:
                normalized[str(cookie["name"])] = str(cookie.get("value", ""))
            else:
                raise HTTPException(status_code=400, detail="Invalid cookies payload")
        return normalized or None

    raise HTTPException(status_code=400, detail="Invalid cookies payload")



def resolve_session_material(request: SessionMaterialRequest) -> dict[str, Any]:
    incoming_session = {
        "session_id": request.session_id,
        "proxy": request.proxy,
        "cookies": normalize_cookies(request.cookies),
        "authorization": request.authorization,
        "thinking_mode": normalize_thinking_mode(request.thinking_mode) if request.thinking_mode is not None else None,
        "model_name": request.model_name.strip() if isinstance(request.model_name, str) and request.model_name.strip() else None,
    }

    if not request.session_id:
        incoming_session["thinking_mode"] = incoming_session["thinking_mode"] or "instant"
        incoming_session["model_name"] = incoming_session["model_name"] or "auto"
        return incoming_session

    stored_session = SESSION_STORE.get(request.session_id, {})
    merged_session = dict(stored_session)
    merged_session["session_id"] = request.session_id
    merged_session["proxy"] = request.proxy or stored_session.get("proxy")

    if incoming_session["cookies"] is not None:
        merged_session["cookies"] = incoming_session["cookies"]
    elif stored_session.get("cookies") is not None:
        merged_session["cookies"] = stored_session["cookies"]

    if incoming_session["authorization"] is not None:
        merged_session["authorization"] = incoming_session["authorization"]
    elif stored_session.get("authorization") is not None:
        merged_session["authorization"] = stored_session["authorization"]

    merged_session["thinking_mode"] = incoming_session["thinking_mode"] or stored_session.get("thinking_mode", "instant")
    merged_session["model_name"] = incoming_session["model_name"] or stored_session.get("model_name", "auto")

    if not merged_session.get("cookies") and not merged_session.get("authorization") and request.session_id not in SESSION_STORE:
        raise HTTPException(status_code=400, detail="Session material is missing for the provided session_id")

    SESSION_STORE[request.session_id] = merged_session
    return merged_session



def build_client(session_material: dict[str, Any]) -> ChatGPT:
    return ChatGPT(
        proxy=session_material.get("proxy"),
        cookies=session_material.get("cookies"),
        authorization=session_material.get("authorization"),
        thinking_mode=session_material.get("thinking_mode", "instant"),
        model_name=session_material.get("model_name", "auto"),
    )



def chat_summary(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
        "message_count": len(chat["messages"]),
    }



def persist_chat(chat: dict[str, Any]) -> None:
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO chats (
                id, title, created_at, updated_at, session_id, thinking_mode, model_name,
                session_material_json, remote_conversation_started, remote_conversation_id, remote_parent_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                session_id=excluded.session_id,
                thinking_mode=excluded.thinking_mode,
                model_name=excluded.model_name,
                session_material_json=excluded.session_material_json,
                remote_conversation_started=excluded.remote_conversation_started,
                remote_conversation_id=excluded.remote_conversation_id,
                remote_parent_message_id=excluded.remote_parent_message_id
            """,
            (
                chat["id"],
                chat["title"],
                chat["created_at"],
                chat["updated_at"],
                chat.get("session_id"),
                chat["thinking_mode"],
                chat["model_name"],
                json.dumps(chat["session_material"]),
                1 if chat.get("remote_conversation_started", False) else 0,
                chat.get("remote_conversation_id"),
                chat.get("remote_parent_message_id"),
            ),
        )
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat["id"],))
        conn.executemany(
            "INSERT INTO messages (id, chat_id, role, content, created_at, image) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    message["id"],
                    chat["id"],
                    message["role"],
                    message["content"],
                    message["created_at"],
                    1 if message.get("image", False) else 0,
                )
                for message in chat["messages"]
            ],
        )
        conn.commit()



def load_chats_from_db() -> None:
    CHAT_STORE.clear()
    with db_connection() as conn:
        chat_rows = conn.execute("SELECT * FROM chats ORDER BY updated_at DESC").fetchall()
        for row in chat_rows:
            message_rows = conn.execute(
                "SELECT id, role, content, created_at, image FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
                (row["id"],),
            ).fetchall()
            chat = {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "messages": [
                    {
                        "id": message_row["id"],
                        "role": message_row["role"],
                        "content": message_row["content"],
                        "created_at": message_row["created_at"],
                        "image": bool(message_row["image"]),
                    }
                    for message_row in message_rows
                ],
                "session_id": row["session_id"],
                "thinking_mode": row["thinking_mode"],
                "model_name": row["model_name"],
                "session_material": json.loads(row["session_material_json"]),
                "remote_conversation_started": bool(row["remote_conversation_started"]),
                "remote_conversation_id": row["remote_conversation_id"],
                "remote_parent_message_id": row["remote_parent_message_id"],
            }
            CHAT_STORE[chat["id"]] = chat
            session_id = chat.get("session_id")
            if session_id:
                SESSION_STORE[session_id] = chat["session_material"]
    print(f"[startup] loaded {len(CHAT_STORE)} chats from {DB_PATH}")



def ensure_chat(chat_id: str) -> dict[str, Any]:
    chat = CHAT_STORE.get(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat



def delete_chat_from_db(chat_id: str) -> None:
    with db_connection() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        conn.commit()



def get_chat_client(chat_id: str, chat: dict[str, Any]) -> ChatGPT:
    client = CHAT_CLIENTS.get(chat_id)
    if client is None:
        client = build_client(chat["session_material"])
        if chat.get("remote_conversation_id"):
            client.data["conversation_id"] = chat["remote_conversation_id"]
        if chat.get("remote_parent_message_id"):
            client.data["parent_message_id"] = chat["remote_parent_message_id"]
        CHAT_CLIENTS[chat_id] = client
    return client



def update_chat_title(chat: dict[str, Any], message: str) -> None:
    if chat["title"] == "New chat":
        trimmed = message.strip()
        chat["title"] = (trimmed[:60] + "…") if len(trimmed) > 60 else trimmed or "New chat"


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    load_chats_from_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/conversation")
async def create_conversation(request: ConversationRequest):
    if not request.message:
        raise HTTPException(status_code=400, detail="Message is required")

    session_material = resolve_session_material(request)

    try:
        client = build_client(session_material)
        if request.image:
            answer: str = client.ask_question(request.message, request.image)
        else:
            answer = client.ask_question(request.message)

        return {
            "status": "success",
            "result": answer,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/chats", response_model=list[ChatSummary])
async def list_chats() -> list[dict[str, Any]]:
    chats = sorted(CHAT_STORE.values(), key=lambda item: item["updated_at"], reverse=True)
    return [chat_summary(chat) for chat in chats]


@app.post("/chats", response_model=ChatDetail)
async def create_chat(request: CreateChatRequest) -> dict[str, Any]:
    session_material = resolve_session_material(request)
    chat_id = str(uuid4())
    now = utc_now_iso()
    chat = {
        "id": chat_id,
        "title": (request.title or "New chat").strip() or "New chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
        "session_id": session_material.get("session_id"),
        "thinking_mode": session_material.get("thinking_mode", "instant"),
        "model_name": session_material.get("model_name", "auto"),
        "session_material": session_material,
        "remote_conversation_started": False,
        "remote_conversation_id": None,
        "remote_parent_message_id": None,
    }
    CHAT_STORE[chat_id] = chat
    persist_chat(chat)
    return {
        **chat_summary(chat),
        "messages": chat["messages"],
        "session_id": chat["session_id"],
        "thinking_mode": chat["thinking_mode"],
        "model_name": chat["model_name"],
    }


@app.get("/chats/{chat_id}", response_model=ChatDetail)
async def get_chat(chat_id: str) -> dict[str, Any]:
    chat = ensure_chat(chat_id)
    return {
        **chat_summary(chat),
        "messages": chat["messages"],
        "session_id": chat["session_id"],
        "thinking_mode": chat["thinking_mode"],
        "model_name": chat["model_name"],
    }


@app.patch("/chats/{chat_id}", response_model=ChatDetail)
async def rename_chat(chat_id: str, request: RenameChatRequest) -> dict[str, Any]:
    chat = ensure_chat(chat_id)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    chat["title"] = title
    chat["updated_at"] = utc_now_iso()
    persist_chat(chat)
    return {
        **chat_summary(chat),
        "messages": chat["messages"],
        "session_id": chat["session_id"],
        "thinking_mode": chat["thinking_mode"],
        "model_name": chat["model_name"],
    }


@app.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str) -> dict[str, str]:
    ensure_chat(chat_id)
    CHAT_STORE.pop(chat_id, None)
    CHAT_CLIENTS.pop(chat_id, None)
    delete_chat_from_db(chat_id)
    return {"status": "success"}


@app.post("/chats/{chat_id}/messages", response_model=ChatDetail)
async def send_chat_message(chat_id: str, request: SendMessageRequest) -> dict[str, Any]:
    if not request.message:
        raise HTTPException(status_code=400, detail="Message is required")

    chat = ensure_chat(chat_id)
    client = get_chat_client(chat_id, chat)

    user_message = {
        "id": str(uuid4()),
        "role": "user",
        "content": request.message,
        "created_at": utc_now_iso(),
        "image": bool(request.image),
    }
    chat["messages"].append(user_message)
    update_chat_title(chat, request.message)

    try:
        if request.image or not chat.get("remote_conversation_started", False):
            answer = client.ask_question(request.message, request.image)
            chat["remote_conversation_started"] = True
        else:
            client.hold_conversation(request.message, new=False)
            answer = client.response

        chat["remote_conversation_id"] = client.data.get("conversation_id")
        chat["remote_parent_message_id"] = client.data.get("parent_message_id")

        assistant_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "content": answer,
            "created_at": utc_now_iso(),
            "image": False,
        }
        chat["messages"].append(assistant_message)
        chat["updated_at"] = utc_now_iso()
        persist_chat(chat)
        return {
            **chat_summary(chat),
            "messages": chat["messages"],
            "session_id": chat["session_id"],
            "thinking_mode": chat["thinking_mode"],
            "model_name": chat["model_name"],
        }
    except HTTPException:
        raise
    except Exception as e:
        chat["messages"].pop()
        persist_chat(chat)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


if __name__ == "__main__":
    init_db()
    load_chats_from_db()
    run(app, host="0.0.0.0", port=6969)
