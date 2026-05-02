from curl_cffi  import requests
from ..logger   import Log
from ..runtime  import Utils


class IP_Info:
    
    @staticmethod
    def _safe_between(main_text: str, value_1: str, value_2: str, default: str = "") -> str:
        try:
            return Utils.between(main_text, value_1, value_2)
        except Exception:
            return default
    
    @staticmethod
    def fetch_info(session: requests.session.Session) -> str:
        
        default_info: list = ["0.0.0.0", "Unknown", "Unknown", "0", "0", "UTC"]
        
        try:
            info_request: requests.models.Response = session.get('https://iplocation.com/')
            info_request_2: requests.models.Response = session.get('https://ipaddresslocation.net/ip-to-timezone')

            ip_infos: list = []
            ip_infos.append(IP_Info._safe_between(info_request.text, '<td><b class="ip">', '<', default_info[0]))
            ip_infos.append(IP_Info._safe_between(info_request.text, '<td class="city">', '<', default_info[1]))
            ip_infos.append(IP_Info._safe_between(info_request.text, '<td><span class="region_name">', '<', default_info[2]))
            ip_infos.append(IP_Info._safe_between(info_request.text, '<td class="lat">', '<', default_info[3]))
            ip_infos.append(IP_Info._safe_between(info_request.text, '<td class="lng">', '<', default_info[4]))
            ip_infos.append(IP_Info._safe_between(info_request_2.text, 'Time Zone:</strong> ', ' ', default_info[5]))

            if len(ip_infos) != 6 or any(value == "" for value in ip_infos):
                raise ValueError("Incomplete IP metadata")

            return ip_infos

        except Exception as exc:
            Log.Info(f"Falling back to default IP metadata: {exc}")
            return default_info
