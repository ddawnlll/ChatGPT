import os
import shutil
import sys
from pathlib import Path


def get_default_browser_executable_path() -> str:
    if sys.platform == "darwin":
        for candidate in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Firefox.app/Contents/MacOS/firefox",
        ):
            if os.path.isfile(candidate):
                return candidate
        return ""

    if sys.platform == "win32":
        for candidate in (
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ):
            if os.path.isfile(candidate):
                return candidate
        return ""

    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "firefox"):
        path = shutil.which(name)
        if path:
            return path
    return ""


def get_default_browser_user_data_dir() -> str:
    executable = get_default_browser_executable_path().lower()
    home = Path.home()

    if sys.platform == "darwin":
        if "brave" in executable:
            return str((home / "Library/Application Support/BraveSoftware/Brave-Browser").resolve())
        if "chrome" in executable:
            return str((home / "Library/Application Support/Google/Chrome").resolve())
        if "chromium" in executable:
            return str((home / "Library/Application Support/Chromium").resolve())
        if "firefox" in executable:
            return str((home / "Library/Application Support/Firefox").resolve())
    elif sys.platform == "win32":
        if "brave" in executable:
            return os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\User Data")
        if "chrome" in executable:
            return os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")
        if "chromium" in executable:
            return os.path.expandvars(r"%LocalAppData%\Chromium\User Data")
        if "firefox" in executable:
            return os.path.expandvars(r"%AppData%\Mozilla\Firefox")
    else:
        if "brave" in executable:
            return str((home / ".config/BraveSoftware/Brave-Browser").resolve())
        if "chrome" in executable:
            return str((home / ".config/google-chrome").resolve())
        if "chromium" in executable:
            return str((home / ".config/chromium").resolve())
        if "firefox" in executable:
            return str((home / ".mozilla/firefox").resolve())

    project_root = Path(__file__).parent.parent
    local_profile = project_root / "data" / "browser_profile"
    return str(local_profile.resolve())
