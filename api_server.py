from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
ALLOWED_TRANSPORT_MODES = {"authenticated", "anon"}
ALLOWED_VERIFICATION_STATES = {"not_checked", "passed", "failed"}


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
    transport_mode: str | None = None
    allow_anon_fallback: bool = False
    endpoint_overrides: dict[str, str] | None = None
    extra_headers: dict[str, str] | None = None
    websocket_url: str | None = None
    websocket_verify_token: str | None = None


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


class VerificationUpdateRequest(BaseModel):
    history_verification: str | None = None
    sidebar_visible: bool | None = None
    title_verification: str | None = None
    missing_browser_stage: str | None = None
    notes: str | None = None


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
    transport_mode: str
    allow_anon_fallback: bool = False
    verification: dict[str, Any] = {}
    last_transport_diagnostics: dict[str, Any] = {}


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
                transport_mode TEXT NOT NULL DEFAULT 'authenticated',
                allow_anon_fallback INTEGER NOT NULL DEFAULT 0,
                session_material_json TEXT NOT NULL,
                remote_conversation_started INTEGER NOT NULL DEFAULT 0,
                remote_conversation_id TEXT,
                remote_parent_message_id TEXT,
                verification_json TEXT NOT NULL DEFAULT '{}',
                last_transport_diagnostics_json TEXT NOT NULL DEFAULT '{}'
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
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(chats)").fetchall()}
        if "transport_mode" not in existing_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN transport_mode TEXT NOT NULL DEFAULT 'authenticated'")
        if "allow_anon_fallback" not in existing_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN allow_anon_fallback INTEGER NOT NULL DEFAULT 0")
        if "verification_json" not in existing_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN verification_json TEXT NOT NULL DEFAULT '{}' ")
        if "last_transport_diagnostics_json" not in existing_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN last_transport_diagnostics_json TEXT NOT NULL DEFAULT '{}' ")
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


def normalize_transport_mode(transport_mode: str | None) -> str:
    normalized = (transport_mode or "authenticated").strip().lower()
    if normalized not in ALLOWED_TRANSPORT_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid transport mode: {transport_mode}")
    return normalized


def normalize_verification_state(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in ALLOWED_VERIFICATION_STATES:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {value}")
    return normalized



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
        "transport_mode": normalize_transport_mode(request.transport_mode) if request.transport_mode is not None else None,
        "allow_anon_fallback": bool(request.allow_anon_fallback),
        "endpoint_overrides": dict(request.endpoint_overrides or {}),
        "extra_headers": dict(request.extra_headers or {}),
        "websocket_url": request.websocket_url,
        "websocket_verify_token": request.websocket_verify_token,
    }

    if not request.session_id:
        incoming_session["thinking_mode"] = incoming_session["thinking_mode"] or "instant"
        incoming_session["model_name"] = incoming_session["model_name"] or "auto"
        incoming_session["transport_mode"] = incoming_session["transport_mode"] or "authenticated"
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
    merged_session["transport_mode"] = incoming_session["transport_mode"] or stored_session.get("transport_mode", "authenticated")
    merged_session["allow_anon_fallback"] = incoming_session["allow_anon_fallback"] or stored_session.get("allow_anon_fallback", False)
    merged_session["endpoint_overrides"] = incoming_session["endpoint_overrides"] or stored_session.get("endpoint_overrides", {})
    merged_session["extra_headers"] = incoming_session["extra_headers"] or stored_session.get("extra_headers", {})
    merged_session["websocket_url"] = incoming_session["websocket_url"] or stored_session.get("websocket_url")
    merged_session["websocket_verify_token"] = incoming_session["websocket_verify_token"] or stored_session.get("websocket_verify_token")

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
        transport_mode=session_material.get("transport_mode", "authenticated"),
        allow_anon_fallback=session_material.get("allow_anon_fallback", False),
        endpoint_overrides=session_material.get("endpoint_overrides"),
        extra_headers=session_material.get("extra_headers"),
        websocket_url=session_material.get("websocket_url"),
        websocket_verify_token=session_material.get("websocket_verify_token"),
    )



def chat_summary(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
        "message_count": len(chat["messages"]),
    }



def chat_detail_payload(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        **chat_summary(chat),
        "messages": chat["messages"],
        "session_id": chat["session_id"],
        "thinking_mode": chat["thinking_mode"],
        "model_name": chat["model_name"],
        "transport_mode": chat["transport_mode"],
        "allow_anon_fallback": chat.get("allow_anon_fallback", False),
        "verification": dict(chat.get("verification", {})),
        "last_transport_diagnostics": dict(chat.get("last_transport_diagnostics", {})),
    }



def update_chat_transport_diagnostics(chat: dict[str, Any], client: ChatGPT) -> None:
    diagnostics = client.get_debug_summary().get("request_diagnostics", {})
    chat["last_transport_diagnostics"] = dict(diagnostics)
    verification = chat.setdefault("verification", {})
    verification.setdefault("history_verification", "not_checked")
    verification.setdefault("title_verification", "not_checked")
    verification.setdefault("sidebar_visible", None)
    verification.setdefault("missing_browser_stage", None)
    verification.setdefault("notes", None)
    verification["remote_conversation_exists"] = bool(diagnostics.get("remote_conversation_id") or chat.get("remote_conversation_id"))



def persist_chat(chat: dict[str, Any]) -> None:
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO chats (
                id, title, created_at, updated_at, session_id, thinking_mode, model_name,
                transport_mode, allow_anon_fallback, session_material_json, remote_conversation_started, remote_conversation_id, remote_parent_message_id,
                verification_json, last_transport_diagnostics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                session_id=excluded.session_id,
                thinking_mode=excluded.thinking_mode,
                model_name=excluded.model_name,
                transport_mode=excluded.transport_mode,
                allow_anon_fallback=excluded.allow_anon_fallback,
                session_material_json=excluded.session_material_json,
                remote_conversation_started=excluded.remote_conversation_started,
                remote_conversation_id=excluded.remote_conversation_id,
                remote_parent_message_id=excluded.remote_parent_message_id,
                verification_json=excluded.verification_json,
                last_transport_diagnostics_json=excluded.last_transport_diagnostics_json
            """,
            (
                chat["id"],
                chat["title"],
                chat["created_at"],
                chat["updated_at"],
                chat.get("session_id"),
                chat["thinking_mode"],
                chat["model_name"],
                chat.get("transport_mode", "authenticated"),
                1 if chat.get("allow_anon_fallback", False) else 0,
                json.dumps(chat["session_material"]),
                1 if chat.get("remote_conversation_started", False) else 0,
                chat.get("remote_conversation_id"),
                chat.get("remote_parent_message_id"),
                json.dumps(chat.get("verification", {})),
                json.dumps(chat.get("last_transport_diagnostics", {})),
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
                "transport_mode": row["transport_mode"] if "transport_mode" in row.keys() else "authenticated",
                "allow_anon_fallback": bool(row["allow_anon_fallback"]) if "allow_anon_fallback" in row.keys() else False,
                "session_material": json.loads(row["session_material_json"]),
                "remote_conversation_started": bool(row["remote_conversation_started"]),
                "remote_conversation_id": row["remote_conversation_id"],
                "remote_parent_message_id": row["remote_parent_message_id"],
                "verification": json.loads(row["verification_json"]) if "verification_json" in row.keys() and row["verification_json"] else {},
                "last_transport_diagnostics": json.loads(row["last_transport_diagnostics_json"]) if "last_transport_diagnostics_json" in row.keys() and row["last_transport_diagnostics_json"] else {},
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


@app.get("/debug/transports/{chat_id}")
async def debug_chat_transport(chat_id: str) -> dict[str, Any]:
    chat = ensure_chat(chat_id)
    client = get_chat_client(chat_id, chat)
    return {
        "chat_id": chat_id,
        "transport_mode": chat.get("transport_mode"),
        "allow_anon_fallback": chat.get("allow_anon_fallback", False),
        "verification": chat.get("verification", {}),
        "last_transport_diagnostics": chat.get("last_transport_diagnostics", {}),
        "session_status": client.get_session_status(),
        "debug_summary": client.get_debug_summary(),
        "transport_audit": client.get_transport_audit(),
    }


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
        "transport_mode": session_material.get("transport_mode", "authenticated"),
        "allow_anon_fallback": session_material.get("allow_anon_fallback", False),
        "session_material": session_material,
        "remote_conversation_started": False,
        "remote_conversation_id": None,
        "remote_parent_message_id": None,
        "verification": {
            "history_verification": "not_checked",
            "title_verification": "not_checked",
            "sidebar_visible": None,
            "missing_browser_stage": None,
            "notes": None,
            "remote_conversation_exists": False,
        },
        "last_transport_diagnostics": {},
    }
    CHAT_STORE[chat_id] = chat
    persist_chat(chat)
    return chat_detail_payload(chat)


@app.get("/chats/{chat_id}", response_model=ChatDetail)
async def get_chat(chat_id: str) -> dict[str, Any]:
    chat = ensure_chat(chat_id)
    return chat_detail_payload(chat)


@app.patch("/chats/{chat_id}", response_model=ChatDetail)
async def rename_chat(chat_id: str, request: RenameChatRequest) -> dict[str, Any]:
    chat = ensure_chat(chat_id)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    chat["title"] = title
    chat["updated_at"] = utc_now_iso()
    persist_chat(chat)
    return chat_detail_payload(chat)


@app.patch("/chats/{chat_id}/verification", response_model=ChatDetail)
async def update_chat_verification(chat_id: str, request: VerificationUpdateRequest) -> dict[str, Any]:
    chat = ensure_chat(chat_id)
    verification = dict(chat.get("verification", {}))

    history_verification = normalize_verification_state(request.history_verification, "history_verification")
    title_verification = normalize_verification_state(request.title_verification, "title_verification")

    if history_verification is not None:
        verification["history_verification"] = history_verification
    if title_verification is not None:
        verification["title_verification"] = title_verification
    if request.sidebar_visible is not None:
        verification["sidebar_visible"] = request.sidebar_visible
    if request.missing_browser_stage is not None:
        verification["missing_browser_stage"] = request.missing_browser_stage.strip() or None
    if request.notes is not None:
        verification["notes"] = request.notes.strip() or None

    chat["verification"] = verification
    chat["updated_at"] = utc_now_iso()
    persist_chat(chat)
    return chat_detail_payload(chat)


@app.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str) -> dict[str, str]:
    ensure_chat(chat_id)
    CHAT_STORE.pop(chat_id, None)
    CHAT_CLIENTS.pop(chat_id, None)
    delete_chat_from_db(chat_id)
    return {"status": "success"}


@app.post("/chats/{chat_id}/messages/stream")
async def stream_chat_message(chat_id: str, request: SendMessageRequest) -> StreamingResponse:
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
    persist_chat(chat)

    def sse_event(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    def event_stream():
        assistant_parts: list[str] = []
        try:
            yield sse_event({"type": "user", "message": user_message})
            if request.image or not chat.get("remote_conversation_started", False):
                chunk_iter = client.stream_question(request.message, request.image)
                chat["remote_conversation_started"] = True
            else:
                chunk_iter = client.hold_conversation_stream(request.message)

            for chunk in chunk_iter:
                assistant_parts.append(chunk)
                yield sse_event({"type": "chunk", "content": chunk})

            chat["remote_conversation_id"] = client.data.get("conversation_id")
            chat["remote_parent_message_id"] = client.data.get("parent_message_id")
            update_chat_transport_diagnostics(chat, client)
            assistant_message = {
                "id": str(uuid4()),
                "role": "assistant",
                "content": "".join(assistant_parts),
                "created_at": utc_now_iso(),
                "image": False,
            }
            chat["messages"].append(assistant_message)
            chat["updated_at"] = utc_now_iso()
            persist_chat(chat)
            yield sse_event({
                "type": "done",
                "chat": chat_detail_payload(chat),
            })
        except Exception as exc:
            if chat["messages"] and chat["messages"][-1]["id"] == user_message["id"]:
                chat["messages"].pop()
                persist_chat(chat)
            yield sse_event({"type": "error", "error": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
        update_chat_transport_diagnostics(chat, client)

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
        return chat_detail_payload(chat)
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
