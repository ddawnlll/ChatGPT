import os
import sys
from pathlib import Path

def get_default_browser_user_data_dir() -> str:
    project_root = Path(__file__).parent.parent
    local_profile = project_root / "data" / "browser_profile"
    return str(local_profile.resolve())

def get_default_browser_executable_path() -> str:
    # Prefer letting Playwright resolve the channel (e.g. 'chrome') instead of hardcoding the path
    return ""
