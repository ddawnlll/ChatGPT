#!/usr/bin/env python3
"""Verify a system browser is available for Playwright automation."""
import os
import shutil
import sys

MACOS_CANDIDATES = [
    ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("Brave Browser", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ("Firefox", "/Applications/Firefox.app/Contents/MacOS/firefox"),
]

LINUX_CANDIDATES = [
    ("Google Chrome", "google-chrome"),
    ("Google Chrome Stable", "google-chrome-stable"),
    ("Brave Browser", "brave-browser"),
    ("Chromium", "chromium"),
    ("Chromium Browser", "chromium-browser"),
    ("Firefox", "firefox"),
]


def iter_candidates():
    override = os.environ.get("CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH")
    if override:
        yield ("Override", override)

    for candidate in MACOS_CANDIDATES:
        yield candidate

    for name, command in LINUX_CANDIDATES:
        resolved = shutil.which(command)
        yield (name, resolved or command)


def exists(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def main():
    print("Checking for system browsers...")
    found = []
    seen = set()
    for name, path in iter_candidates():
        if path in seen:
            continue
        seen.add(path)

        if exists(path):
            print(f"  ✓ {name}: {path}")
            found.append((name, path))
        else:
            print(f"  ✗ {name}: not found")

    if not found:
        print("\n✗ No supported browser found!")
        print("  Install Google Chrome, Brave, Chromium, or Firefox.")
        print("  Or set CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH=/path/to/browser")
        sys.exit(1)

    default_name, default_path = found[0]
    print(f"\n✓ Default browser: {default_name}")
    print(f"  Path: {default_path}")
    print("\n  Override with: CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH=/path/to/browser")


if __name__ == "__main__":
    main()
