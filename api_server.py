from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from uvicorn import run

from wrapper import ChatGPT


app = FastAPI()
SESSION_STORE: dict[str, dict[str, Any]] = {}
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


class ConversationRequest(BaseModel):
    proxy: str | None = None
    message: str
    image: str | None = None
    session_id: str | None = None
    cookies: str | list[CookieItem] | dict[str, str] | None = None
    authorization: str | None = None
    thinking_mode: str | None = None


def normalize_thinking_mode(thinking_mode: str | None) -> str:
    normalized = (thinking_mode or "instant").strip().lower()
    if normalized not in ALLOWED_THINKING_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid thinking mode: {thinking_mode}")
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


def resolve_session_material(request: ConversationRequest) -> dict[str, Any]:
    incoming_session = {
        "session_id": request.session_id,
        "cookies": normalize_cookies(request.cookies),
        "authorization": request.authorization,
        "thinking_mode": normalize_thinking_mode(request.thinking_mode) if request.thinking_mode is not None else None,
    }

    if not request.session_id:
        incoming_session["thinking_mode"] = incoming_session["thinking_mode"] or "instant"
        return incoming_session

    stored_session = SESSION_STORE.get(request.session_id, {})
    merged_session = dict(stored_session)
    merged_session["session_id"] = request.session_id

    if incoming_session["cookies"] is not None:
        merged_session["cookies"] = incoming_session["cookies"]
    elif stored_session.get("cookies") is not None:
        merged_session["cookies"] = stored_session["cookies"]

    if incoming_session["authorization"] is not None:
        merged_session["authorization"] = incoming_session["authorization"]
    elif stored_session.get("authorization") is not None:
        merged_session["authorization"] = stored_session["authorization"]

    if incoming_session["thinking_mode"] is not None:
        merged_session["thinking_mode"] = incoming_session["thinking_mode"]
    else:
        merged_session["thinking_mode"] = stored_session.get("thinking_mode", "instant")

    if not merged_session.get("cookies") and not merged_session.get("authorization") and request.session_id not in SESSION_STORE:
        raise HTTPException(status_code=400, detail="Session material is missing for the provided session_id")

    SESSION_STORE[request.session_id] = merged_session
    return merged_session


def build_client(session_material: dict[str, Any]) -> ChatGPT:
    return ChatGPT(
        cookies=session_material.get("cookies"),
        authorization=session_material.get("authorization"),
        thinking_mode=session_material.get("thinking_mode", "instant"),
    )


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
            answer: str = client.ask_question(request.message)

        return {
            "status": "success",
            "result": answer,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=6969)
