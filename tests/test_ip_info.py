import importlib

ip_info_mod = importlib.import_module("wrapper.IP_Info.ip_info")


class DummyResponse:
    def __init__(self, text):
        self.text = text


class DummySession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        resp = self.responses.get(url)
        if isinstance(resp, Exception):
            raise resp
        return DummyResponse(resp)


def test_fetch_info_returns_parsed_values_when_available():
    session = DummySession(
        {
            "https://iplocation.com/": (
                '<td><b class="ip">1.2.3.4<'
                '<td class="city">City<'
                '<td><span class="region_name">Region<'
                '<td class="lat">12.34<'
                '<td class="lng">56.78<'
            ),
            "https://ipaddresslocation.net/ip-to-timezone": "Time Zone:</strong> UTC something",
        }
    )

    info = ip_info_mod.IP_Info.fetch_info(session)
    assert info == ["1.2.3.4", "City", "Region", "12.34", "56.78", "UTC"]


def test_fetch_info_falls_back_when_parsing_fails():
    session = DummySession(
        {
            "https://iplocation.com/": "broken html",
            "https://ipaddresslocation.net/ip-to-timezone": "broken html",
        }
    )

    info = ip_info_mod.IP_Info.fetch_info(session)
    assert info == ["0.0.0.0", "Unknown", "Unknown", "0", "0", "UTC"]


def test_fetch_info_falls_back_when_request_fails():
    session = DummySession(
        {
            "https://iplocation.com/": RuntimeError("network error"),
        }
    )

    info = ip_info_mod.IP_Info.fetch_info(session)
    assert info == ["0.0.0.0", "Unknown", "Unknown", "0", "0", "UTC"]
