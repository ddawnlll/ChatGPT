from json import load
from pathlib import Path

from wrapper import ChatGPT


def load_session(path: str = "session.json") -> dict:
    session_path = Path(path)
    if not session_path.exists():
        return {}

    with session_path.open("r", encoding="utf-8") as handle:
        return load(handle)


def main() -> None:
    session = load_session()

    client = ChatGPT(
        cookies=session.get("cookies"),
        authorization=session.get("authorization"),
        thinking_mode=session.get("thinking_mode", "extended"),
        model_name=session.get("model_name", "auto"),
        transport_mode=session.get("transport_mode", "anon"),
        allow_anon_fallback=bool(session.get("allow_anon_fallback", False)),
    )

    message = session.get("message", "Test")
    image = session.get("image")
    print(client.ask_question(message, image))


if __name__ == "__main__":
    main()
