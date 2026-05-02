from json import load
from pathlib import Path

from wrapper import ChatGPT


def load_session_fixture(path: str = "session.json") -> dict:
    fixture_path = Path(path)
    if not fixture_path.exists():
        return {}

    with fixture_path.open("r", encoding="utf-8") as handle:
        return load(handle)


def build_client_from_fixture(session_data: dict) -> ChatGPT:
    return ChatGPT(
        cookies=session_data.get("cookies"),
        authorization=session_data.get("authorization"),
        thinking_mode=session_data.get("thinking_mode", "instant"),
    )


def main() -> None:
    session_data = load_session_fixture()
    if not session_data:
        print(ChatGPT().ask_question("Test"))
        return

    client = build_client_from_fixture(session_data)
    message = session_data.get("message", "Test")
    print(client.ask_question(message))


if __name__ == "__main__":
    main()
