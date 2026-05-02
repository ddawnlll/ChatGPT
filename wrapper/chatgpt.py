from wrapper      import Log, Utils, Headers, Challenges, VM, IP_Info
from random       import randint, random, choice
from zoneinfo     import ZoneInfo
from curl_cffi    import requests
from datetime     import datetime
from uuid         import uuid4
from json         import loads
from time         import time
from typing       import Any
from base64       import b64decode
from mimetypes    import guess_type
from PIL import Image
from io import BytesIO

class ChatGPT:
    def __init__(self, proxy: str=None, cookies: dict = None, authorization: str = None, thinking_mode: str = "instant", model_name: str = "auto") -> Any:
        self.session: requests.session.Session = requests.Session(impersonate="chrome133a")
        self.session.headers = Headers.DEFAULT
        self.data: dict = {}
        self.authorization: str = authorization
        self.thinking_mode: str = self._normalize_thinking_mode(thinking_mode)
        self.model_name: str = self._normalize_model_name(model_name)
        if self.authorization:
            self.session.headers.update({
                'Authorization': self.authorization
            })

        if proxy:
            
            self.session.proxies = {
                "all": proxy # format http://user:pass@ip:port
            }
            
        self.ip_info: list = IP_Info.fetch_info(self.session)
        self.timezone_offset: int = int(datetime.now(ZoneInfo(self.ip_info[5])).utcoffset().total_seconds() / 60)
        self._proxy_supplied: bool = bool(proxy)
        self._supplied_cookies: Any = cookies
        self.session_status: dict = {}
        self.last_request_summary: dict = {'request_sent': False}
        self.last_response_summary: dict = {'response_received': False}
        self.reacts: list = [
            "location",
            "__reactContainer$" + self._generate_react(),
            "_reactListening" + self._generate_react(),
        ]
        self.window_keys: list = [
            "0",
            "window",
            "self",
            "document",
            "name",
            "location",
            "customElements",
            "history",
            "navigation",
            "locationbar",
            "menubar",
            "personalbar",
            "scrollbars",
            "statusbar",
            "toolbar",
            "status",
            "closed",
            "frames",
            "length",
            "top",
            "opener",
            "parent",
            "frameElement",
            "navigator",
            "origin",
            "external",
            "screen",
            "innerWidth",
            "innerHeight",
            "scrollX",
            "pageXOffset",
            "scrollY",
            "pageYOffset",
            "visualViewport",
            "screenX",
            "screenY",
            "outerWidth",
            "outerHeight",
            "devicePixelRatio",
            "event",
            "clientInformation",
            "screenLeft",
            "screenTop",
            "styleMedia",
            "onsearch",
            "trustedTypes",
            "performance",
            "onappinstalled",
            "onbeforeinstallprompt",
            "crypto",
            "indexedDB",
            "sessionStorage",
            "localStorage",
            "onbeforexrselect",
            "onabort",
            "onbeforeinput",
            "onbeforematch",
            "onbeforetoggle",
            "onblur",
            "oncancel",
            "oncanplay",
            "oncanplaythrough",
            "onchange",
            "onclick",
            "onclose",
            "oncontentvisibilityautostatechange",
            "oncontextlost",
            "oncontextmenu",
            "oncontextrestored",
            "oncuechange",
            "ondblclick",
            "ondrag",
            "ondragend",
            "ondragenter",
            "ondragleave",
            "ondragover",
            "ondragstart",
            "ondrop",
            "ondurationchange",
            "onemptied",
            "onended",
            "onerror",
            "onfocus",
            "onformdata",
            "oninput",
            "oninvalid",
            "onkeydown",
            "onkeypress",
            "onkeyup",
            "onload",
            "onloadeddata",
            "onloadedmetadata",
            "onloadstart",
            "onmousedown",
            "onmouseenter",
            "onmouseleave",
            "onmousemove",
            "onmouseout",
            "onmouseover",
            "onmouseup",
            "onmousewheel",
            "onpause",
            "onplay",
            "onplaying",
            "onprogress",
            "onratechange",
            "onreset",
            "onresize",
            "onscroll",
            "onsecuritypolicyviolation",
            "onseeked",
            "onseeking",
            "onselect",
            "onslotchange",
            "onstalled",
            "onsubmit",
            "onsuspend",
            "ontimeupdate",
            "ontoggle",
            "onvolumechange",
            "onwaiting",
            "onwebkitanimationend",
            "onwebkitanimationiteration",
            "onwebkitanimationstart",
            "onwebkittransitionend",
            "onwheel",
            "onauxclick",
            "ongotpointercapture",
            "onlostpointercapture",
            "onpointerdown",
            "onpointermove",
            "onpointerrawupdate",
            "onpointerup",
            "onpointercancel",
            "onpointerover",
            "onpointerout",
            "onpointerenter",
            "onpointerleave",
            "onselectstart",
            "onselectionchange",
            "onanimationend",
            "onanimationiteration",
            "onanimationstart",
            "ontransitionrun",
            "ontransitionstart",
            "ontransitionend",
            "ontransitioncancel",
            "onafterprint",
            "onbeforeprint",
            "onbeforeunload",
            "onhashchange",
            "onlanguagechange",
            "onmessage",
            "onmessageerror",
            "onoffline",
            "ononline",
            "onpagehide",
            "onpageshow",
            "onpopstate",
            "onrejectionhandled",
            "onstorage",
            "onunhandledrejection",
            "onunload",
            "isSecureContext",
            "crossOriginIsolated",
            "scheduler",
            "alert",
            "atob",
            "blur",
            "btoa",
            "cancelAnimationFrame",
            "cancelIdleCallback",
            "captureEvents",
            "clearInterval",
            "clearTimeout",
            "close",
            "confirm",
            "createImageBitmap",
            "fetch",
            "find",
            "focus",
            "getComputedStyle",
            "getSelection",
            "matchMedia",
            "moveBy",
            "moveTo",
            "open",
            "postMessage",
            "print",
            "prompt",
            "queueMicrotask",
            "releaseEvents",
            "reportError",
            "requestAnimationFrame",
            "requestIdleCallback",
            "resizeBy",
            "resizeTo",
            "scroll",
            "scrollBy",
            "scrollTo",
            "setInterval",
            "setTimeout",
            "stop",
            "structuredClone",
            "webkitCancelAnimationFrame",
            "webkitRequestAnimationFrame",
            "chrome",
            "caches",
            "cookieStore",
            "ondevicemotion",
            "ondeviceorientation",
            "ondeviceorientationabsolute",
            "sharedStorage",
            "documentPictureInPicture",
            "fetchLater",
            "getScreenDetails",
            "queryLocalFonts",
            "showDirectoryPicker",
            "showOpenFilePicker",
            "showSaveFilePicker",
            "originAgentCluster",
            "viewport",
            "onpageswap",
            "onpagereveal",
            "credentialless",
            "fence",
            "launchQueue",
            "speechSynthesis",
            "oncommand",
            "onscrollend",
            "onscrollsnapchange",
            "onscrollsnapchanging",
            "webkitRequestFileSystem",
            "webkitResolveLocalFileSystemURL",
            "define",
            "ethereum",
            "__oai_SSR_HTML",
            "__reactRouterContext",
            "$RC",
            "__oai_SSR_TTI",
            "__reactRouterManifest",
            "__reactRouterVersion",
            "DD_RUM",
            "__REACT_INTL_CONTEXT__",
            "regeneratorRuntime",
            "DD_LOGS",
            "__STATSIG__",
            "__mobxInstanceCount",
            "__mobxGlobals",
            "_g",
            "__reactRouterRouteModules",
            "__SEGMENT_INSPECTOR__",
            "__reactRouterDataRouter",
            "MotionIsMounted",
            "_oaiHandleSessionExpired"
        ]
        
        if not cookies:
            self._fetch_cookies()
        else:
            self.session.cookies.update(self._normalize_cookies(cookies))
            self._fetch_cookies()

        self._update_session_status(self._proxy_supplied, self._supplied_cookies)
            
    def _normalize_cookies(self, cookies: Any) -> dict:
        if isinstance(cookies, dict):
            return cookies

        if isinstance(cookies, str):
            normalized: dict = {}
            for item in cookies.split(';'):
                if '=' not in item:
                    continue
                name, value = item.split('=', 1)
                name = name.strip()
                value = value.strip()
                if name:
                    normalized[name] = value
            return normalized

        if isinstance(cookies, list):
            normalized: dict = {}
            for cookie in cookies:
                if isinstance(cookie, dict) and cookie.get('name') is not None:
                    normalized[str(cookie['name'])] = str(cookie.get('value', ''))
            return normalized

        return {}

    def _normalize_thinking_mode(self, thinking_mode: str) -> str:
        allowed_modes = {'instant', 'extended', 'pro'}
        normalized_mode = (thinking_mode or 'instant').strip().lower()
        if normalized_mode not in allowed_modes:
            raise ValueError(f"Unsupported thinking_mode: {thinking_mode}")
        return normalized_mode

    def _normalize_model_name(self, model_name: str) -> str:
        normalized_model = (model_name or 'auto').strip()
        if not normalized_model:
            return 'auto'
        return normalized_model

    def _has_identity_cookie(self, cookie_names: list[str]) -> bool:
        identity_cookie_names = {'oai-did', '__Secure-oai-is'}
        identity_cookie_prefixes = ('__Secure-next-auth.session-token',)
        return any(
            name in identity_cookie_names or any(name.startswith(prefix) for prefix in identity_cookie_prefixes)
            for name in cookie_names
        )

    def _update_session_status(self, proxy_supplied: bool, supplied_cookies: Any) -> None:
        normalized_supplied_cookies = self._normalize_cookies(supplied_cookies) if supplied_cookies else {}
        supplied_cookie_names = list(normalized_supplied_cookies.keys())
        current_cookie_names = list(self.session.cookies.keys())
        has_supplied_identity_cookie = self._has_identity_cookie(supplied_cookie_names)
        has_current_identity_cookie = self._has_identity_cookie(current_cookie_names)
        device_id_present = bool(self.session.cookies.get('oai-did'))
        session_material_loaded = bool(supplied_cookies) or bool(self.authorization)

        login_reasons: list[str] = []
        if not session_material_loaded:
            login_reasons.append('no session material supplied')
        if session_material_loaded and not bool(self.authorization):
            login_reasons.append('authorization not supplied; cookie presence alone is not sufficient for verification')
        if session_material_loaded and not (has_supplied_identity_cookie or bool(self.authorization)):
            login_reasons.append('no recognizable identity cookie or authorization supplied')
        if session_material_loaded and not device_id_present:
            login_reasons.append('oai-did cookie missing after bootstrap')

        login_state = 'LIKELY_AUTHENTICATED' if session_material_loaded and bool(self.authorization) and device_id_present else 'NOT_VERIFIED'
        if login_state == 'LIKELY_AUTHENTICATED':
            login_reasons = []

        self.session_status = {
            'proxy_supplied': proxy_supplied,
            'cookies_supplied': bool(supplied_cookies),
            'authorization_supplied': bool(self.authorization),
            'thinking_mode': self.thinking_mode,
            'model_name': self.model_name,
            'device_id_present': device_id_present,
            'session_material_loaded': session_material_loaded,
            'supplied_identity_cookie_present': has_supplied_identity_cookie,
            'current_identity_cookie_present': has_current_identity_cookie,
            'login_state': login_state,
            'login_reasons': login_reasons,
            'bootstrap_ready': True,
        }

    def get_session_status(self) -> dict:
        return dict(self.session_status)

    def get_debug_summary(self) -> dict:
        return {
            'session_status': dict(self.session_status),
            'last_request_summary': dict(self.last_request_summary),
            'last_response_summary': dict(self.last_response_summary),
        }

    def _generate_react(self) -> str:
        n = random() 
        base36 = ''
        chars = '0123456789abcdefghijklmnopqrstuvwxyz'
        x = int(n * 36**10)
        for _ in range(10):
            x, r = divmod(x, 36)
            base36 = chars[r] + base36
        return base36
    
    def _safe_extract(self, text: str, start: str, end: str) -> str | None:
        try:
            return Utils.between(text, start, end)
        except Exception:
            return None

    def _parse_event_stream(self, stream_data: str) -> str:
        result: list = []
        lines: list = stream_data.strip().split('\n')
        
        for line in lines:
            if line.startswith('data:'):
                
                data_str: str = line[5:].strip()
                
                if data_str == '[DONE]':
                    break
                
                data: dict = loads(data_str)
                
                if isinstance(data, dict):
                    
                    if data.get('o') == 'append' and data.get('p') == '/message/content/parts/0':
                        
                        result.append(data.get('v'))
                        
                    elif data.get('o') == 'patch' and isinstance(data.get('v'), list):
                        
                        for op in data.get('v'):
                            
                            if op.get('o') == 'append' and op.get('p') == '/message/content/parts/0':
                                
                                result.append(op.get('v'))
                                
                    elif 'v' in data and isinstance(data['v'], str):
                        result.append(data['v'])

        return ''.join(result)
        
    def _fetch_cookies(self) -> None:
        
        load_site: requests.models.Response = self.session.get("https://chatgpt.com")
        self.session.cookies.update(load_site.cookies)

        self.data["prod"] = load_site.text.split('data-build="')[1].split('"')[0]
        self.data["device-id"] = self.session.cookies.get("oai-did")
        
        self.start_time: int = int(time() * 1000)
        self.sid: str = str(uuid4())
        
        self.data["config"] = self._get_config(randint(800, 1400))
    
    def _get_tokens(self, process_time: int=randint(1400, 2000)) -> None:
        
        self.session.headers = Headers.REQUIREMENTS
        self.session.headers.update({
            'oai-client-version': self.data["prod"],
            'oai-device-id': self.data["device-id"],
            'Authorization': self.authorization
        })
        
        p_value: str = Challenges.generate_token(self.data["config"])
        self.data["vm_token"] = p_value
        self.data["config"] = self._get_config(process_time)
        
        requirements_data: dict = {
            'p': p_value,
        }
        
        requirements_request: requests.models.Response = self.session.post('https://chatgpt.com/backend-anon/sentinel/chat-requirements', json=requirements_data)

        if requirements_request.status_code == 200:
            self.data["token"] = requirements_request.json().get("token")
            self.data["proofofwork"] = requirements_request.json().get("proofofwork")
            self.data["bytecode"] = requirements_request.json().get("turnstile").get("dx")
        
        else:
            Log.Error("Something went wrong while fetching chat requirements")

    def _get_config(self, process_time: int) -> None:
        return [
            4880,
            datetime.now(ZoneInfo(self.ip_info[5])).strftime(f"%a %b %d %Y %H:%M:%S GMT%z ({datetime.now(ZoneInfo(self.ip_info[5])).tzname()})"),
            4294705152,
            random(),
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            None,
            self.data["prod"],
            "de-DE",
            "de-DE,de,en-US,en",
            random(),
            "webkitGetUserMedia−function webkitGetUserMedia() { [native code] }",
            choice(self.reacts),
            choice(self.window_keys),
            process_time + random(),
            self.sid,
            "",
            20,
            self.start_time
        ]

    def get_conduit(self, next: bool = False) -> str:
        self.session.headers = Headers.CONDUIT
        self.session.headers.update({
            'oai-client-version': self.data["prod"],
            'oai-device-id': self.data["device-id"],
            'Authorization': self.authorization
        })

        if not next:
            post_data: dict = {
                'action': 'next',
                'fork_from_shared_post': False,
                'parent_message_id': 'client-created-root',
                'model': 'auto',
                'timezone_offset_min': self.timezone_offset,
                'timezone': self.ip_info[5],
                'history_and_training_disabled': True,
                'conversation_mode': {
                    'kind': 'primary_assistant',
                },
                'system_hints': [],
                'supports_buffering': True,
                'supported_encodings': [
                    'v1',
                ],
            }
        
        else:
            post_data: dict = {
                'action': 'next',
                'fork_from_shared_post': False,
                'conversation_id': self.data["conversation_id"],
                'parent_message_id': self.data["parent_message_id"],
                'model': 'auto',
                'timezone_offset_min': self.timezone_offset,
                'timezone': self.ip_info[5],
                'history_and_training_disabled': True,
                'conversation_mode': {
                    'kind': 'primary_assistant',
                },
                'system_hints': [],
                'supports_buffering': True,
                'supported_encodings': [
                    'v1',
                ],
            }
                    
        conduit_request: requests.models.Response = self.session.post('https://chatgpt.com/backend-anon/f/conversation/prepare', json=post_data)
        
        if '"status":"ok"' in conduit_request.text:
            return conduit_request.json().get("conduit_token")
        
        else:
            Log.Error("Something went wrong while fetching conduit token: ")
            Log.Error(conduit_request.text)
            return None
    
    def start_conversation(self, message: str) -> None:
        return self.ask_question_with_file(message)

    def upload_file(self, file_name: str, file_b64: str, is_image: bool = False, is_zip: bool = False) -> None:
        self.session.headers = Headers.REQUIREMENTS
        self.session.headers.update({
            'oai-client-version': self.data["prod"],
            'oai-device-id': self.data["device-id"],
            'Authorization': self.authorization
        })

        if file_b64.startswith("data:"):
            file_b64 = file_b64.split(",")[1]

        file_size: int = len(b64decode(file_b64))
        use_case: str = 'ace_upload' if is_zip else 'my_files'
        width, height = None, None
        if is_image:
            width, height = Image.open(BytesIO(b64decode(file_b64))).size
            use_case = 'multimodal'

        file_data: dict = {
            'file_name': file_name,
            'file_size': file_size,
            'use_case': use_case,
            'timezone_offset_min': self.timezone_offset,
            'reset_rate_limits': False,
        }
        file_request: requests.models.Response = self.session.post('https://chatgpt.com/backend-anon/files', json=file_data)
        file_id: str = file_request.json().get("file_id")
        upload_url: str = file_request.json().get("upload_url")

        self.session.headers = Headers.FILE
        self.session.headers.update({
            'Authorization': self.authorization
        })
        upload_request: requests.models.Response = self.session.put(upload_url, data=b64decode(file_b64))

        self.session.headers = Headers.REQUIREMENTS
        self.session.headers.update({
            'oai-client-version': self.data["prod"],
            'oai-device-id': self.data["device-id"],
            'Authorization': self.authorization
        })

        process_data: dict = {
            'file_id': file_id,
            'use_case': use_case,
            'index_for_retrieval': False,
            'file_name': file_name,
        }

        process_request: requests.models.Response = self.session.post('https://chatgpt.com/backend-anon/files/process_upload_stream', json=process_data)
        if "Succeeded processing " in process_request.text:
            return file_id, file_size, width, height
        else:
            Log.Error("Something went wrong while uploading file")
            return None
        
    def start_with_image(self, message: str, file_name: str, image: str) -> None:
        self.ask_question_with_file(message, file_name, image)
    
    def hold_conversation(self, message: str, new: bool = True) -> None:
        self.index = 2000
        
        if new:
            self.start_conversation(message)
        
        conduit_token: str = self.get_conduit(next=True)
        
        self._get_tokens(randint(self.index, self.index + 1000))
        self.index += 3000
        
        time_1: int = randint(self.index, self.index + 3000)
        proof_token: str = Challenges.solve_pow(self.data["proofofwork"]["seed"], self.data["proofofwork"]["difficulty"], self.data["config"])
        
        turnstile_token: str = VM.get_turnstile(self.data["bytecode"], self.data["vm_token"], str(self.ip_info[:-1]))


        self.session.headers = Headers.CONVERSATION
        self.session.headers.update({
            'oai-client-version': self.data["prod"],
            'oai-device-id': self.data["device-id"],
            'oai-echo-logs': f'0,{time_1},1,{time_1 + randint(1000, 1200)}',
            'openai-sentinel-chat-requirements-token': self.data["token"],
            'openai-sentinel-proof-token': proof_token,
            'openai-sentinel-turnstile-token': turnstile_token,
            'x-conduit-token': conduit_token,
            'Authorization': self.authorization
        })
        
        if new:
            new_message: str = input("Prompt: ")
        else:
            new_message: str = message
        
        conversation_data: dict = {
            'action': 'next',
            'messages': [
                {
                    'id': str(uuid4()),
                    'author': {
                        'role': 'user',
                    },
                    'create_time': round(time(), 3),
                    'content': {
                        'content_type': 'text',
                        'parts': [
                            new_message,
                        ],
                    },
                    'metadata': {
                        'selected_github_repos': [],
                        'selected_all_github_repos': False,
                        'serialization_metadata': {
                            'custom_symbol_offsets': [],
                        },
                    },
                },
            ],
            'conversation_id': self.data["conversation_id"],
            'parent_message_id': self.data["parent_message_id"],
            'model': 'auto',
            'timezone_offset_min': self.timezone_offset,
            'timezone': self.ip_info[5],
            'history_and_training_disabled': True,
            'conversation_mode': {
                'kind': 'primary_assistant',
            },
            'enable_message_followups': True,
            'system_hints': [],
            'supports_buffering': True,
            'supported_encodings': [
                'v1',
            ],
            'client_contextual_info': {
                'is_dark_mode': True,
                'time_since_loaded': 17,
                'page_height': 1219,
                'page_width': 3440,
                'pixel_ratio': 1,
                'screen_height': 1440,
                'screen_width': 3440,
            },
            'paragen_cot_summary_display_override': 'allow',
            'force_parallel_switch': 'auto',
        }
        
        conversation_request: requests.models.Response = self.session.post('https://chatgpt.com/backend-anon/f/conversation', json=conversation_data)
        self.session.cookies.update(conversation_request.cookies)
        
        if 'Unusual activity' in conversation_request.text:
            Log.Error("Your IP got flagged by chatgpt, retry with a new IP")
            exit(conversation_request.status_code)
        
        conversation_id = self._safe_extract(conversation_request.text, '"conversation_id": "', '"')
        parent_message_id = self._safe_extract(conversation_request.text, '"message_id": "', '"')
        if conversation_id:
            self.data["conversation_id"] = conversation_id
        if parent_message_id:
            self.data["parent_message_id"] = parent_message_id
        
        self.response = self._parse_event_stream(conversation_request.text)
    
    def ask_question(self, message: str, image: str = None) -> str:
        
        if not image:
            self.ask_question_with_file(message)
        else:
            file_name = f"{str(uuid4())}.png"
            self.ask_question_with_file(message, file_name=file_name, file_b64=image, is_image=True)
        
        return self.response

    def ask_question_with_file(self, message: str, model: str | None = None, file_name: str = None, file_b64: str = None, is_image: bool = False) -> str:
        model = model or self.model_name
        self._get_tokens()
        conduit_token: str = self.get_conduit()

        time_1: int = randint(6000, 9000)
        proof_token: str = Challenges.solve_pow(self.data["proofofwork"]["seed"], self.data["proofofwork"]["difficulty"], self.data["config"])
        turnstile_token: str = VM.get_turnstile(self.data["bytecode"], self.data["vm_token"], str(self.ip_info[:-1]))

        self.session.headers = Headers.CONVERSATION
        self.session.headers.update({
            'oai-client-version': self.data["prod"],
            'oai-device-id': self.data["device-id"],
            'oai-echo-logs': f'0,{time_1},1,{time_1 + randint(1000, 1200)}',
            'openai-sentinel-chat-requirements-token': self.data["token"],
            'openai-sentinel-proof-token': proof_token,
            'openai-sentinel-turnstile-token': turnstile_token,
            'x-conduit-token': conduit_token,
            'Authorization': self.authorization
        })

        
        msg = {
            'id': str(uuid4()),
            'author': {
                'role': 'user',
            },
            'create_time': round(time(), 3),
            'metadata': {
                'selected_github_repos': [],
                'selected_all_github_repos': False,
                'selected_sources': [],
                'serialization_metadata': {
                    'custom_symbol_offsets': [],
                },
            },
        }

        is_image = False
        is_zip = False

        if file_name and file_b64:
            mime_type = guess_type(file_name)[0]
            is_zip = file_name.endswith('.zip')
            is_image = file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'))
            mime_type = "application/zip" if is_zip else "image/png" if is_image else mime_type
            
            file_id, file_size, width, height = self.upload_file(file_name, file_b64, is_image=is_image, is_zip=is_zip)

            attachment = {
                'id': file_id,
                'size': file_size,
                'name': file_name,
                'mime_type': mime_type,
                'source': 'local',
            }
            if is_image:
                attachment.update({
                    'width': width,
                    'height': height,
                })

            msg['metadata']['attachments'] = [attachment]

        if is_image:
            msg["content"] = {
                'content_type': 'multimodal_text',
                'parts': [
                    {
                        'content_type': 'image_asset_pointer',
                        'asset_pointer': f'file-service://{file_id}',
                        'size_bytes': file_size,
                        'width': width,
                        'height': height,
                    },
                    message,
                ],
            }
        else:
            msg["content"] = {
                'content_type': 'text',
                'parts': [
                    message,
                ],
            }

        conversation_data: dict = {
            'action': 'next',
            'messages': [
                msg,
            ],
            'parent_message_id': 'client-created-root',
            'model': model,
            'effort': self.thinking_mode,
            'timezone_offset_min': self.timezone_offset,
            'timezone': self.ip_info[5],
            'history_and_training_disabled': True,
            'conversation_mode': {
                'kind': 'primary_assistant',
            },
            'enable_message_followups': True,
            'system_hints': [],
            'supports_buffering': True,
            'supported_encodings': [
                'v1',
            ],
            'client_contextual_info': {
                'is_dark_mode': True,
                'time_since_loaded': randint(3, 6),
                'page_height': 1219,
                'page_width': 3440,
                'pixel_ratio': 1,
                'screen_height': 1440,
                'screen_width': 3440,
            },
            'paragen_cot_summary_display_override': 'allow',
            'force_parallel_switch': 'auto',
        }

        self.last_request_summary = {
            'request_sent': True,
            'url': 'https://chatgpt.com/backend-anon/f/conversation',
            'model': model,
            'thinking_mode': self.thinking_mode,
            'message_length': len(message),
            'has_image': is_image,
            'authorization_supplied': bool(self.authorization),
            'cookies_supplied': bool(self._supplied_cookies),
            'conversation_id_present_before_send': bool(self.data.get('conversation_id')),
        }

        conversation_request: requests.models.Response = self.session.post('https://chatgpt.com/backend-anon/f/conversation', json=conversation_data, timeout=(30, 300))
        self.session.cookies.update(conversation_request.cookies)
        self.last_response_summary = {
            'response_received': True,
            'status_code': getattr(conversation_request, 'status_code', None),
            'text_preview': conversation_request.text[:300],
            'unusual_activity': 'Unusual activity' in conversation_request.text,
            'conversation_id_found': '"conversation_id": "' in conversation_request.text,
            'message_id_found': '"message_id": "' in conversation_request.text,
        }
        
        if 'Unusual activity' in conversation_request.text:
            Log.Error("Your IP got flagged by chatgpt, retry with a new IP")
            exit(conversation_request.status_code)
        
        conversation_id = self._safe_extract(conversation_request.text, '"conversation_id": "', '"')
        parent_message_id = self._safe_extract(conversation_request.text, '"message_id": "', '"')
        if conversation_id:
            self.data["conversation_id"] = conversation_id
        if parent_message_id:
            self.data["parent_message_id"] = parent_message_id
        self.response = self._parse_event_stream(conversation_request.text)
        if not self.response and not conversation_id:
            preview = conversation_request.text[:300]
            raise RuntimeError(f"Conversation response did not contain a usable answer or conversation id. Preview: {preview}")
        return self.response
