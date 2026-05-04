import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transport_runtime import PlaywrightTransport


@pytest.fixture
def playwright_transport() -> PlaywrightTransport:
    return PlaywrightTransport({"transport_mode": "playwright", "browser_user_data_dir": "/tmp/profile"})


@pytest.fixture
def daemon_events():
    def _daemon_events(*events):
        return iter(events)

    return _daemon_events
