#!/usr/bin/env python3
"""Verify a system browser is available for Playwright automation."""
import os
import sys
from pathlib import Path

CANDIDATES = [
    ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("Brave Browser", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ("Chromium",      "/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ("Firefox",       "/Applications/Firefox.app/Contents/MacOS/firefox"),
]

def main():
    print("Checking for system browsers...")
    found = []
    for name, path in CANDIDATES:
        if os.path.isfile(path):
            print(f"  ✓ {name}: {path}")
            found.append((name, path))
        else:
            print(f"  ✗ {name}: not found")

    if not found:
        print("\n✗ No supported browser found!")
        print("  Install Google Chrome, Brave, Chromium, or Firefox.")
        sys.exit(1)

    default_name, default_path = found[0]
    print(f"\n✓ Default browser: {default_name}")
    print(f"  Path: {default_path}")
    print(f"\n  Override with: CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH=/path/to/browser")

if __name__ == "__main__":
    main()
