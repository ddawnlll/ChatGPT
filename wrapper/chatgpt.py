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
    ANON_ENDPOINTS = {
        'requirements': 'https://chatgpt.com/backend-anon/sentinel/chat-requirements',
        'prepare_conversation': 'https://chatgpt.com/backend-anon/f/conversation/prepare',
        'conversation': 'https://chatgpt.com/backend-anon/f/conversation',
        'files': 'https://chatgpt.com/backend-anon/files',
        'process_upload_stream': 'https://chatgpt.com/backend-anon/files/process_upload_stream',
    }
    ANON_HEADER_INVENTORY = {
        'requirements': ['oai-client-version', 'oai-device-id', 'Authorization'],
        'prepare_conversation': ['oai-client-version', 'oai-device-id', 'Authorization'],
        'conversation': [
            'oai-client-version',
            'oai-device-id',
            'oai-echo-logs',
            'openai-sentinel-chat-requirements-token',
            'openai-sentinel-proof-token',
            'openai-sentinel-turnstile-token',
            'x-conduit-token',
            'Authorization',
        ],
        'files': ['oai-client-version', 'oai-device-id', 'Authorization'],
        'process_upload_stream': ['oai-client-version', 'oai-device-id', 'Authorization'],
        'file_upload_put': ['Authorization'],
    }
    ANON_PAYLOAD_AUDIT = {
        'history_suppressing_fields': ['history_and_training_disabled'],
        'account-history-risk_fields': ['history_and_training_disabled'],
        'shared_conversation_fields': [
            'action',
            'messages',
            'conversation_id',
            'parent_message_id',
            'model',
            'effort',
            'timezone_offset_min',
            'timezone',
            'conversation_mode',
            'enable_message_followups',
            'system_hints',
            'supports_buffering',
            'supported_encodings',
            'client_contextual_info',
            'paragen_cot_summary_display_override',
            'force_parallel_switch',
        ],
        'prepare_payload_fields': [
            'action',
            'fork_from_shared_post',
            'parent_message_id',
            'conversation_id',
            'model',
            'timezone_offset_min',
            'timezone',
            'history_and_training_disabled',
            'conversation_mode',
            'system_hints',
            'supports_buffering',
            'supported_encodings',
        ],
        'file_payload_fields': ['file_name', 'file_size', 'use_case', 'timezone_offset_min', 'reset_rate_limits'],
        'process_upload_fields': ['file_id', 'use_case', 'index_for_retrieval', 'file_name'],
    }
    ANON_FLOW_STAGES = [
        'bootstrap_cookies_and_client_version',
        'requirements_token_and_turnstile_bootstrap',
        'prepare_conversation_conduit_token',
        'optional_file_create_upload_process',
        'initial_or_followup_conversation_send',
        'event_stream_parse_and_state_extraction',
    ]
    AUTHENTICATED_ENDPOINT_SLOTS = {
        'requirements': 'https://chatgpt.com/backend-api/sentinel/chat-requirements/prepare',
        'requirements_finalize': 'https://chatgpt.com/backend-api/sentinel/chat-requirements/finalize',
        'requirements_ping': 'https://chatgpt.com/backend-api/sentinel/ping',
        'sentinel_req': 'https://chatgpt.com/backend-api/sentinel/req',
        'prepare_conversation': 'https://chatgpt.com/backend-api/f/conversation/prepare',
        'conversation': 'https://chatgpt.com/backend-api/f/conversation',
        'files': 'https://chatgpt.com/backend-api/files',
        'process_upload_stream': 'https://chatgpt.com/backend-api/files/process_upload_stream',
        'file_download': 'https://chatgpt.com/backend-api/files/download/{file_id}',
        'stream_status': 'https://chatgpt.com/backend-api/conversation/{conversation_id}/stream_status',
        'textdocs': 'https://chatgpt.com/backend-api/conversation/{conversation_id}/textdocs',
        'history_sync': 'https://chatgpt.com/backend-api/conversations',
        'title_sync': None,
    }

    def __init__(self, proxy: str=None, cookies: dict = None, authorization: str = None, thinking_mode: str = "instant", model_name: str = "auto", transport_mode: str = "authenticated", allow_anon_fallback: bool = False, endpoint_overrides: dict[str, str] | None = None, extra_headers: dict[str, str] | None = None) -> Any:
        self.session: requests.session.Session = requests.Session(impersonate="chrome133a")
        self.session.headers = Headers.DEFAULT
        self.data: dict = {}
        self.authorization: str = authorization
        self.thinking_mode: str = self._normalize_thinking_mode(thinking_mode)
        self.model_name: str = self._normalize_model_name(model_name)
        self.transport_mode: str = self._normalize_transport_mode(transport_mode)
        self.allow_anon_fallback: bool = bool(allow_anon_fallback)
        self.endpoint_overrides: dict[str, str] = dict(endpoint_overrides or {})
        self.extra_headers: dict[str, str] = dict(extra_headers or {})
        if self.authorization:
            self.session.headers.update({
                'Authorization': self.authorization
            })
        if self.extra_headers:
            self.session.headers.update(self.extra_headers)

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
        self.request_diagnostics: dict = {
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': self.transport_mode,
            'endpoint_family': None,
            'remote_conversation_id': None,
            'remote_parent_message_id': None,
            'fallback_occurred': False,
            'history_verification': 'not_checked',
            'missing_requirements': [],
        }
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

    def _normalize_transport_mode(self, transport_mode: str) -> str:
        normalized_mode = (transport_mode or 'authenticated').strip().lower()
        if normalized_mode not in {'authenticated', 'anon'}:
            raise ValueError(f"Unsupported transport_mode: {transport_mode}")
        return normalized_mode

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
            'transport_mode': self.transport_mode,
            'allow_anon_fallback': self.allow_anon_fallback,
            'endpoint_override_keys': sorted(self.endpoint_overrides.keys()),
            'extra_header_keys': sorted(self.extra_headers.keys()),
            'device_id_present': device_id_present,
            'client_version_present': bool(self.data.get('prod')),
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
            'request_diagnostics': dict(self.request_diagnostics),
        }

    def _update_request_diagnostics(self, **updates: Any) -> None:
        self.request_diagnostics.update(updates)
        if self.data.get('conversation_id'):
            self.request_diagnostics['remote_conversation_id'] = self.data.get('conversation_id')
        if self.data.get('parent_message_id'):
            self.request_diagnostics['remote_parent_message_id'] = self.data.get('parent_message_id')

    def get_transport_audit(self) -> dict:
        return {
            'selected_transport_mode': self.transport_mode,
            'allow_anon_fallback': self.allow_anon_fallback,
            'anon_endpoints': dict(self.ANON_ENDPOINTS),
            'anon_header_inventory': dict(self.ANON_HEADER_INVENTORY),
            'anon_payload_audit': dict(self.ANON_PAYLOAD_AUDIT),
            'anon_flow_stages': list(self.ANON_FLOW_STAGES),
            'authenticated_endpoint_slots': dict(self.AUTHENTICATED_ENDPOINT_SLOTS),
            'diagnostics': dict(self.request_diagnostics),
            'endpoint_overrides': dict(self.endpoint_overrides),
            'extra_headers': sorted(self.extra_headers.keys()),
        }

    def _endpoint_for(self, endpoint_name: str) -> str:
        if self.request_diagnostics.get('effective_transport_mode') == 'anon' or self.transport_mode == 'anon':
            return self.ANON_ENDPOINTS[endpoint_name]

        if endpoint_name in self.endpoint_overrides:
            return self.endpoint_overrides[endpoint_name]

        endpoint = self.AUTHENTICATED_ENDPOINT_SLOTS.get(endpoint_name)
        if endpoint:
            return endpoint
        raise NotImplementedError(
            f"Authenticated endpoint discovery is incomplete for '{endpoint_name}'. "
            "Capture logged-in browser traffic before enabling this path."
        )

    def _missing_authenticated_requirements(self) -> list[str]:
        missing: list[str] = []
        if not self._supplied_cookies:
            missing.append('cookies')
        if not (self.authorization or self._supplied_cookies):
            missing.append('authorization or authenticated cookies')
        if not self.data.get('device-id'):
            missing.append('device/client header source: oai-device-id')
        if not self.data.get('prod'):
            missing.append('device/client header source: oai-client-version')
        return missing

    def _activate_anon_fallback(self, missing: list[str], reason: str) -> None:
        self._update_request_diagnostics(
            effective_transport_mode='anon',
            endpoint_family='backend-anon',
            fallback_occurred=True,
            missing_requirements=missing,
        )
        self.last_request_summary = {
            'request_sent': False,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': 'anon',
            'endpoint_family': 'backend-anon',
            'fallback_occurred': True,
            'missing_requirements': missing,
            'reason': reason,
        }

    def _ensure_transport_ready(self, action: str) -> None:
        if self.transport_mode == 'anon':
            self._update_request_diagnostics(
                effective_transport_mode='anon',
                endpoint_family='backend-anon',
                fallback_occurred=False,
                missing_requirements=[],
            )
            return

        missing = self._missing_authenticated_requirements()
        self._update_request_diagnostics(
            effective_transport_mode='authenticated',
            endpoint_family='authenticated-web',
            fallback_occurred=False,
            missing_requirements=missing,
        )
        self.last_request_summary = {
            'request_sent': False,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': 'authenticated',
            'endpoint_family': 'authenticated-web',
            'fallback_occurred': False,
            'missing_requirements': missing,
            'action': action,
        }

        if missing:
            if self.allow_anon_fallback:
                self._activate_anon_fallback(missing, f'authenticated preflight failed before {action}')
                return
            raise RuntimeError(
                'Authenticated transport preflight failed; missing required session material: ' + ', '.join(missing)
            )

        return

    def _headers_for(self, stage: str, extra: dict[str, Any] | None = None, authenticated: bool | None = None) -> dict[str, str]:
        authenticated = self.request_diagnostics.get('effective_transport_mode') == 'authenticated' if authenticated is None else authenticated
        templates = {
            'default': Headers.DEFAULT,
            'requirements': Headers.REQUIREMENTS,
            'prepare_conversation': Headers.CONDUIT,
            'conversation': Headers.CONVERSATION,
            'files': Headers.REQUIREMENTS,
            'process_upload_stream': Headers.REQUIREMENTS,
            'file_upload_put': Headers.FILE,
        }
        headers = dict(templates.get(stage, Headers.DEFAULT))
        common = {
            'oai-client-version': self.data.get('prod'),
            'oai-device-id': self.data.get('device-id'),
        }
        if authenticated:
            common['oai-language'] = headers.get('oai-language', 'de-DE')
        if self.authorization:
            common['Authorization'] = self.authorization
        headers.update({key: value for key, value in common.items() if value})
        if extra:
            headers.update({key: str(value) for key, value in extra.items() if value is not None})
        return headers

    def _set_headers_for(self, stage: str, extra: dict[str, Any] | None = None, authenticated: bool | None = None) -> None:
        self.session.headers = self._headers_for(stage, extra=extra, authenticated=authenticated)

    def _authenticated_headers(self, accept: str = 'text/event-stream') -> dict[str, str]:
        return self._headers_for(
            'conversation',
            extra={'accept': accept, 'content-type': 'application/json'},
            authenticated=True,
        )

    def _build_message_payload(self, message: str, file_name: str = None, file_b64: str = None, is_image: bool = False) -> tuple[dict, bool]:
        msg = {
            'id': str(uuid4()),
            'author': {'role': 'user'},
            'create_time': round(time(), 3),
            'metadata': {
                'selected_github_repos': [],
                'selected_all_github_repos': False,
                'selected_sources': [],
                'serialization_metadata': {'custom_symbol_offsets': []},
            },
        }

        if file_name and file_b64:
            mime_type = guess_type(file_name)[0]
            is_zip = file_name.endswith('.zip')
            is_image = file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'))
            mime_type = 'application/zip' if is_zip else 'image/png' if is_image else mime_type
            file_id, file_size, width, height = self.upload_file(file_name, file_b64, is_image=is_image, is_zip=is_zip)
            attachment = {'id': file_id, 'size': file_size, 'name': file_name, 'mime_type': mime_type, 'source': 'local'}
            if is_image:
                attachment.update({'width': width, 'height': height})
            msg['metadata']['attachments'] = [attachment]
            if is_image:
                msg['content'] = {
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
                return msg, True

        msg['content'] = {'content_type': 'text', 'parts': [message]}
        return msg, False

    def _authenticated_client_contextual_info(self) -> dict:
        return {
            'is_dark_mode': True,
            'time_since_loaded': randint(3, 6),
            'page_height': 1219,
            'page_width': 3440,
            'pixel_ratio': 1,
            'screen_height': 1440,
            'screen_width': 3440,
        }

    def _authenticated_prepare_payload(self, message: str, model: str, file_name: str = None) -> dict:
        payload = {
            'action': 'next',
            'fork_from_shared_post': False,
            'parent_message_id': self.data.get('parent_message_id') or 'client-created-root',
            'model': model,
            'timezone_offset_min': self.timezone_offset,
            'timezone': self.ip_info[5],
            'conversation_mode': {'kind': 'primary_assistant'},
            'system_hints': [],
            'supports_buffering': True,
            'supported_encodings': ['v1'],
            'client_contextual_info': self._authenticated_client_contextual_info(),
            'client_prepare_state': 'none',
            'thinking_effort': self.thinking_mode,
        }
        if message:
            payload['partial_query'] = {
                'id': str(uuid4()),
                'author': {'role': 'user'},
                'content': {'content_type': 'text', 'parts': [message[:1]]},
            }
        if self.data.get('conversation_id'):
            payload['conversation_id'] = self.data['conversation_id']
        if file_name:
            mime_type = guess_type(file_name)[0]
            if mime_type:
                payload['attachment_mime_types'] = [mime_type]
        return payload

    def _authenticated_conversation_payload(self, message: str, model: str, file_name: str = None, file_b64: str = None, is_image: bool = False, client_prepare_state: str = 'success') -> tuple[dict, bool]:
        msg, has_image = self._build_message_payload(message, file_name, file_b64, is_image)
        payload = {
            'action': 'next',
            'messages': [msg],
            'parent_message_id': self.data.get('parent_message_id') or 'client-created-root',
            'model': model,
            'thinking_effort': self.thinking_mode,
            'timezone_offset_min': self.timezone_offset,
            'timezone': self.ip_info[5],
            'conversation_mode': {'kind': 'primary_assistant'},
            'enable_message_followups': True,
            'system_hints': [],
            'supports_buffering': True,
            'supported_encodings': ['v1'],
            'client_contextual_info': self._authenticated_client_contextual_info(),
            'client_prepare_state': client_prepare_state,
            'paragen_cot_summary_display_override': 'allow',
            'force_parallel_switch': 'auto',
        }
        if self.data.get('conversation_id'):
            payload['conversation_id'] = self.data['conversation_id']
        return payload, has_image

    def _extract_conversation_state(self, text: str) -> tuple[str | None, str | None]:
        conversation_id = self._safe_extract(text, '"conversation_id": "', '"') or self._safe_extract(text, '"conversation_id":"', '"')
        message_id = self._safe_extract(text, '"message_id": "', '"') or self._safe_extract(text, '"message_id":"', '"')
        return conversation_id, message_id

    def _extract_authenticated_stream_metadata(self, text: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            'stream_handoff_found': False,
            'resume_token_found': False,
            'turn_exchange_id': None,
        }
        for line in text.splitlines():
            if not line.startswith('data:'):
                continue
            data_str = line[5:].strip()
            if not data_str or data_str == '[DONE]':
                continue
            try:
                data = loads(data_str)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get('type') == 'stream_handoff':
                metadata['stream_handoff_found'] = True
                metadata['turn_exchange_id'] = data.get('turn_exchange_id')
                if data.get('turn_exchange_id'):
                    self.data['turn_exchange_id'] = data.get('turn_exchange_id')
            if data.get('type') == 'resume_conversation_token':
                metadata['resume_token_found'] = bool(data.get('token'))
                if data.get('token'):
                    self.data['resume_conversation_token'] = data.get('token')
        return metadata

    def _apply_conversation_state_from_text(self, text: str) -> tuple[str | None, str | None]:
        conversation_id, parent_message_id = self._extract_conversation_state(text)
        if conversation_id:
            self.data['conversation_id'] = conversation_id
        if parent_message_id:
            self.data['parent_message_id'] = parent_message_id
        self._update_request_diagnostics(
            remote_conversation_id=self.data.get('conversation_id'),
            remote_parent_message_id=self.data.get('parent_message_id'),
        )
        return conversation_id, parent_message_id

    def _record_conversation_request(self, url: str, model: str, message: str, has_image: bool, stream: bool = False) -> None:
        self._update_request_diagnostics(endpoint_family='authenticated-web')
        self.last_request_summary = {
            'request_sent': True,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': self.request_diagnostics.get('effective_transport_mode'),
            'endpoint_family': 'authenticated-web',
            'fallback_occurred': self.request_diagnostics.get('fallback_occurred', False),
            'url': url,
            'model': model,
            'thinking_mode': self.thinking_mode,
            'message_length': len(message),
            'has_image': has_image,
            'stream': stream,
            'authorization_supplied': bool(self.authorization),
            'cookies_supplied': bool(self._supplied_cookies),
            'conversation_id_present_before_send': bool(self.data.get('conversation_id')),
            'history_and_training_disabled_sent': False,
        }

    def _authenticated_chat_requirements(self) -> dict:
        self._set_headers_for('requirements', authenticated=True)
        p_value = Challenges.generate_token(self.data['config'])
        self.data['vm_token'] = p_value
        self.data['config'] = self._get_config(randint(1400, 2000))
        prepare_request = self.session.post(self._endpoint_for('requirements'), json={'p': p_value}, timeout=(30, 120))
        if prepare_request.status_code and prepare_request.status_code >= 400:
            raise RuntimeError(f"Authenticated requirements prepare failed with status {prepare_request.status_code}. Preview: {prepare_request.text[:300]}")
        prepared = prepare_request.json()
        proof_token = Challenges.solve_pow(
            prepared.get('proofofwork', {}).get('seed'),
            prepared.get('proofofwork', {}).get('difficulty'),
            self.data['config'],
        )
        turnstile_dx = (prepared.get('turnstile') or {}).get('dx')
        turnstile_token = VM.get_turnstile(turnstile_dx, p_value, str(self.ip_info[:-1])) if turnstile_dx else None
        finalize_payload = {
            'prepare_token': prepared.get('prepare_token'),
            'proofofwork': proof_token,
            'turnstile': turnstile_token,
        }
        self._set_headers_for('requirements', authenticated=True)
        finalize_request = self.session.post(self._endpoint_for('requirements_finalize'), json=finalize_payload, timeout=(30, 120))
        if finalize_request.status_code and finalize_request.status_code >= 400:
            raise RuntimeError(f"Authenticated requirements finalize failed with status {finalize_request.status_code}. Preview: {finalize_request.text[:300]}")
        finalized = finalize_request.json()
        token = finalized.get('token')
        if not token:
            raise RuntimeError(f"Authenticated requirements finalize response did not include token. Preview: {finalize_request.text[:300]}")
        self.data['token'] = token
        self.data['proof_token'] = proof_token
        self.data['turnstile_token'] = turnstile_token
        return {
            'chat_requirements_token': token,
            'proof_token': proof_token,
            'turnstile_token': turnstile_token,
        }

    def _authenticated_prepare_conversation(self, message: str, model: str, file_name: str = None) -> str:
        payload = self._authenticated_prepare_payload(message, model, file_name=file_name)
        self._set_headers_for('prepare_conversation', authenticated=True)
        prepare_request = self.session.post(self._endpoint_for('prepare_conversation'), json=payload, timeout=(30, 120))
        if prepare_request.status_code and prepare_request.status_code >= 400:
            raise RuntimeError(f"Authenticated conversation prepare failed with status {prepare_request.status_code}. Preview: {prepare_request.text[:300]}")
        prepared = prepare_request.json()
        conduit_token = prepared.get('conduit_token')
        if not conduit_token:
            raise RuntimeError(f"Authenticated conversation prepare response did not include conduit_token. Preview: {prepare_request.text[:300]}")
        self.data['conduit_token'] = conduit_token
        return conduit_token

    def _authenticated_send_initial(self, message: str, model: str | None = None, file_name: str = None, file_b64: str = None, is_image: bool = False):
        model = model or self.model_name
        conduit_token = self._authenticated_prepare_conversation(message, model, file_name=file_name)
        requirements = self._authenticated_chat_requirements()
        payload, has_image = self._authenticated_conversation_payload(message, model, file_name, file_b64, is_image)
        url = self._endpoint_for('conversation')
        self._set_headers_for('conversation', extra={
            'openai-sentinel-chat-requirements-token': requirements['chat_requirements_token'],
            'openai-sentinel-proof-token': requirements['proof_token'],
            'openai-sentinel-turnstile-token': requirements['turnstile_token'],
            'x-conduit-token': conduit_token,
        }, authenticated=True)
        self._record_conversation_request(url, model, message, has_image)
        conversation_request = self.session.post(url, json=payload, timeout=(30, 300))
        self.session.cookies.update(conversation_request.cookies)
        text = conversation_request.text
        conversation_id, parent_message_id = self._apply_conversation_state_from_text(text)
        stream_metadata = self._extract_authenticated_stream_metadata(text)
        self._update_request_diagnostics(**stream_metadata)
        self.last_response_summary = {
            'response_received': True,
            'status_code': getattr(conversation_request, 'status_code', None),
            'text_preview': text[:300],
            'unusual_activity': 'Unusual activity' in text,
            'conversation_id_found': bool(conversation_id),
            'message_id_found': bool(parent_message_id),
            **stream_metadata,
        }
        if 'Unusual activity' in text:
            Log.Error('Your IP got flagged by chatgpt, retry with a new IP')
            exit(conversation_request.status_code)
        self.response = self._parse_event_stream(text)
        if not self.response and not conversation_id:
            raise RuntimeError(f"Authenticated conversation response did not contain a usable answer or conversation id. Preview: {text[:300]}")
        return self.response

    def _authenticated_send_followup(self, message: str, model: str | None = None):
        return self._authenticated_send_initial(message, model=model)

    def _authenticated_stream_initial(self, message: str, model: str | None = None, file_name: str = None, file_b64: str = None, is_image: bool = False):
        model = model or self.model_name
        conduit_token = self._authenticated_prepare_conversation(message, model, file_name=file_name)
        requirements = self._authenticated_chat_requirements()
        payload, has_image = self._authenticated_conversation_payload(message, model, file_name, file_b64, is_image)
        url = self._endpoint_for('conversation')
        self._set_headers_for('conversation', extra={
            'openai-sentinel-chat-requirements-token': requirements['chat_requirements_token'],
            'openai-sentinel-proof-token': requirements['proof_token'],
            'openai-sentinel-turnstile-token': requirements['turnstile_token'],
            'x-conduit-token': conduit_token,
        }, authenticated=True)
        self._record_conversation_request(url, model, message, has_image, stream=True)
        conversation_request = self.session.post(url, json=payload, timeout=(30, 300), stream=True)
        yield from self._consume_stream_response(conversation_request)

    def _authenticated_stream_followup(self, message: str, model: str | None = None):
        yield from self._authenticated_stream_initial(message, model=model)

    def _authenticated_upload_file(self, file_name: str, file_b64: str, is_image: bool = False, is_zip: bool = False):
        if file_b64.startswith('data:'):
            file_b64 = file_b64.split(',', 1)[1]
        raw_file = b64decode(file_b64)
        file_size = len(raw_file)
        use_case = 'ace_upload' if is_zip else 'my_files'
        width, height = None, None
        if is_image:
            width, height = Image.open(BytesIO(raw_file)).size
            use_case = 'multimodal'

        file_data = {
            'file_name': file_name,
            'file_size': file_size,
            'use_case': use_case,
            'timezone_offset_min': self.timezone_offset,
            'reset_rate_limits': False,
        }
        self._set_headers_for('files', authenticated=True)
        create_request = self.session.post(self._endpoint_for('files'), json=file_data, timeout=(30, 120))
        created = create_request.json()
        file_id = created.get('file_id') or created.get('id')
        upload_url = created.get('upload_url')
        if not file_id or not upload_url:
            raise RuntimeError(f"Authenticated file create response did not include file_id/upload_url. Preview: {create_request.text[:300]}")

        self.session.put(upload_url, data=raw_file, timeout=(30, 300))
        process_data = {
            'file_id': file_id,
            'use_case': use_case,
            'index_for_retrieval': False,
            'file_name': file_name,
        }
        process_request = self.session.post(self._endpoint_for('process_upload_stream'), json=process_data, timeout=(30, 300))
        if process_request.status_code and process_request.status_code >= 400:
            raise RuntimeError(f"Authenticated file processing failed with status {process_request.status_code}. Preview: {process_request.text[:300]}")
        return file_id, file_size, width, height

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

    def _extract_stream_chunks(self, line: str) -> list[str]:
        if not line.startswith('data:'):
            return []

        data_str: str = line[5:].strip()
        if data_str == '[DONE]':
            return []

        try:
            data: Any = loads(data_str)
        except Exception:
            return []

        chunks: list[str] = []
        if isinstance(data, dict):
            if data.get('o') == 'append' and data.get('p') == '/message/content/parts/0' and isinstance(data.get('v'), str):
                chunks.append(data.get('v'))
            elif data.get('o') == 'patch' and isinstance(data.get('v'), list):
                for op in data.get('v'):
                    if op.get('o') == 'append' and op.get('p') == '/message/content/parts/0' and isinstance(op.get('v'), str):
                        chunks.append(op.get('v'))
            elif data.get('type') in {'delta', 'content_delta', 'text_delta'} and isinstance(data.get('delta'), str):
                chunks.append(data['delta'])
            elif data.get('type') in {'message_delta', 'content_part'} and isinstance(data.get('text'), str):
                chunks.append(data['text'])
            elif data.get('type') == 'message' and isinstance(data.get('message'), dict):
                chunks.extend(self._extract_text_from_content_tree(data['message']))
            elif data.get('type') in {'stream_handoff', 'resume_conversation_token'}:
                return []
            elif 'v' in data and isinstance(data['v'], str):
                chunks.append(data['v'])
        return chunks

    def _extract_text_from_content_tree(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            content = value.get('content')
            if isinstance(content, dict):
                parts = content.get('parts')
                if isinstance(parts, list):
                    return [part for part in parts if isinstance(part, str)]
            text = value.get('text')
            if isinstance(text, str):
                return [text]
            result: list[str] = []
            for nested in value.values():
                result.extend(self._extract_text_from_content_tree(nested))
            return result
        if isinstance(value, list):
            result: list[str] = []
            for item in value:
                result.extend(self._extract_text_from_content_tree(item))
            return result
        return []

    def _parse_event_stream(self, stream_data: str) -> str:
        result: list = []
        lines: list = stream_data.strip().split('\n')
        
        for line in lines:
            result.extend(self._extract_stream_chunks(line))

        return ''.join(result)

    def _consume_stream_response(self, conversation_request: Any):
        raw_lines: list[str] = []
        response_parts: list[str] = []

        for line in conversation_request.iter_lines():
            if isinstance(line, bytes):
                line = line.decode('utf-8', errors='ignore')
            if line is None:
                continue
            raw_lines.append(line)
            chunks = self._extract_stream_chunks(line)
            for chunk in chunks:
                response_parts.append(chunk)
                yield chunk

        raw_text = '\n'.join(raw_lines)
        self.session.cookies.update(conversation_request.cookies)
        conversation_id_preview, message_id_preview = self._extract_conversation_state(raw_text)
        stream_metadata = self._extract_authenticated_stream_metadata(raw_text)
        self.last_response_summary = {
            'response_received': True,
            'status_code': getattr(conversation_request, 'status_code', None),
            'text_preview': raw_text[:300],
            'unusual_activity': 'Unusual activity' in raw_text,
            'conversation_id_found': bool(conversation_id_preview),
            'message_id_found': bool(message_id_preview),
            **stream_metadata,
        }

        if 'Unusual activity' in raw_text:
            Log.Error("Your IP got flagged by chatgpt, retry with a new IP")
            exit(conversation_request.status_code)

        conversation_id, _ = self._apply_conversation_state_from_text(raw_text)
        self._update_request_diagnostics(**stream_metadata)

        self.response = ''.join(response_parts)
        if not self.response and not conversation_id:
            raise RuntimeError(f"Conversation response did not contain a usable answer or conversation id. Preview: {raw_text[:300]}")
        
    def _fetch_cookies(self) -> None:
        
        load_site: requests.models.Response = self.session.get("https://chatgpt.com")
        self.session.cookies.update(load_site.cookies)

        self.data["prod"] = load_site.text.split('data-build="')[1].split('"')[0]
        self.data["device-id"] = self.session.cookies.get("oai-did")
        
        self.start_time: int = int(time() * 1000)
        self.sid: str = str(uuid4())
        
        self.data["config"] = self._get_config(randint(800, 1400))
    
    def _get_tokens(self, process_time: int=randint(1400, 2000)) -> None:
        
        self._set_headers_for('requirements')
        
        p_value: str = Challenges.generate_token(self.data["config"])
        self.data["vm_token"] = p_value
        self.data["config"] = self._get_config(process_time)
        
        requirements_data: dict = {
            'p': p_value,
        }
        
        requirements_request: requests.models.Response = self.session.post(self._endpoint_for('requirements'), json=requirements_data)

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
        self._set_headers_for('prepare_conversation')

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
                    
        conduit_request: requests.models.Response = self.session.post(self._endpoint_for('prepare_conversation'), json=post_data)
        
        if '"status":"ok"' in conduit_request.text:
            return conduit_request.json().get("conduit_token")
        
        else:
            Log.Error("Something went wrong while fetching conduit token: ")
            Log.Error(conduit_request.text)
            return None
    
    def start_conversation(self, message: str) -> None:
        self._ensure_transport_ready('start_conversation')
        return self.ask_question_with_file(message)

    def upload_file(self, file_name: str, file_b64: str, is_image: bool = False, is_zip: bool = False) -> None:
        self._ensure_transport_ready('upload_file')
        if self.request_diagnostics.get('effective_transport_mode') == 'authenticated':
            return self._authenticated_upload_file(file_name, file_b64, is_image=is_image, is_zip=is_zip)

        self._set_headers_for('files')

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
        file_request: requests.models.Response = self.session.post(self._endpoint_for('files'), json=file_data)
        file_id: str = file_request.json().get("file_id")
        upload_url: str = file_request.json().get("upload_url")

        self._set_headers_for('file_upload_put')
        upload_request: requests.models.Response = self.session.put(upload_url, data=b64decode(file_b64))

        self._set_headers_for('process_upload_stream')

        process_data: dict = {
            'file_id': file_id,
            'use_case': use_case,
            'index_for_retrieval': False,
            'file_name': file_name,
        }

        process_request: requests.models.Response = self.session.post(self._endpoint_for('process_upload_stream'), json=process_data)
        if "Succeeded processing " in process_request.text:
            return file_id, file_size, width, height
        else:
            Log.Error("Something went wrong while uploading file")
            return None
        
    def start_with_image(self, message: str, file_name: str, image: str) -> None:
        self.ask_question_with_file(message, file_name, image)
    
    def hold_conversation(self, message: str, new: bool = True) -> None:
        self._ensure_transport_ready('hold_conversation')
        if self.request_diagnostics.get('effective_transport_mode') == 'authenticated':
            self._authenticated_send_initial(message)
            return

        self.index = 2000
        
        if new:
            self.start_conversation(message)
        
        conduit_token: str = self.get_conduit(next=True)
        
        self._get_tokens(randint(self.index, self.index + 1000))
        self.index += 3000
        
        time_1: int = randint(self.index, self.index + 3000)
        proof_token: str = Challenges.solve_pow(self.data["proofofwork"]["seed"], self.data["proofofwork"]["difficulty"], self.data["config"])
        
        turnstile_token: str = VM.get_turnstile(self.data["bytecode"], self.data["vm_token"], str(self.ip_info[:-1]))


        self._set_headers_for('conversation', extra={
            'oai-echo-logs': f'0,{time_1},1,{time_1 + randint(1000, 1200)}',
            'openai-sentinel-chat-requirements-token': self.data["token"],
            'openai-sentinel-proof-token': proof_token,
            'openai-sentinel-turnstile-token': turnstile_token,
            'x-conduit-token': conduit_token,
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
        
        self._update_request_diagnostics(endpoint_family='backend-anon')
        self.last_request_summary = {
            'request_sent': True,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': self.request_diagnostics.get('effective_transport_mode'),
            'endpoint_family': 'backend-anon',
            'fallback_occurred': self.request_diagnostics.get('fallback_occurred', False),
            'url': 'https://chatgpt.com/backend-anon/f/conversation',
            'model': 'auto',
            'thinking_mode': self.thinking_mode,
            'message_length': len(new_message),
            'has_image': False,
            'authorization_supplied': bool(self.authorization),
            'cookies_supplied': bool(self._supplied_cookies),
            'conversation_id_present_before_send': bool(self.data.get('conversation_id')),
        }
        conversation_request: requests.models.Response = self.session.post(self._endpoint_for('conversation'), json=conversation_data)
        self.session.cookies.update(conversation_request.cookies)
        
        if 'Unusual activity' in conversation_request.text:
            Log.Error("Your IP got flagged by chatgpt, retry with a new IP")
            exit(conversation_request.status_code)
        
        self._apply_conversation_state_from_text(conversation_request.text)
        
        self.response = self._parse_event_stream(conversation_request.text)

    def hold_conversation_stream(self, message: str):
        self._ensure_transport_ready('hold_conversation_stream')
        if self.request_diagnostics.get('effective_transport_mode') == 'authenticated':
            yield from self._authenticated_stream_initial(message)
            return

        conduit_token: str = self.get_conduit(next=True)
        self._get_tokens(randint(2000, 3000))
        time_1: int = randint(3000, 6000)
        proof_token: str = Challenges.solve_pow(self.data["proofofwork"]["seed"], self.data["proofofwork"]["difficulty"], self.data["config"])
        turnstile_token: str = VM.get_turnstile(self.data["bytecode"], self.data["vm_token"], str(self.ip_info[:-1]))

        self._set_headers_for('conversation', extra={
            'oai-echo-logs': f'0,{time_1},1,{time_1 + randint(1000, 1200)}',
            'openai-sentinel-chat-requirements-token': self.data["token"],
            'openai-sentinel-proof-token': proof_token,
            'openai-sentinel-turnstile-token': turnstile_token,
            'x-conduit-token': conduit_token,
        })

        conversation_data = {
            'action': 'next',
            'messages': [{
                'id': str(uuid4()),
                'author': {'role': 'user'},
                'create_time': round(time(), 3),
                'content': {'content_type': 'text', 'parts': [message]},
                'metadata': {
                    'selected_github_repos': [],
                    'selected_all_github_repos': False,
                    'serialization_metadata': {'custom_symbol_offsets': []},
                },
            }],
            'conversation_id': self.data["conversation_id"],
            'parent_message_id': self.data["parent_message_id"],
            'model': self.model_name,
            'timezone_offset_min': self.timezone_offset,
            'timezone': self.ip_info[5],
            'history_and_training_disabled': True,
            'conversation_mode': {'kind': 'primary_assistant'},
            'enable_message_followups': True,
            'system_hints': [],
            'supports_buffering': True,
            'supported_encodings': ['v1'],
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

        self._update_request_diagnostics(endpoint_family='backend-anon')
        self.last_request_summary = {
            'request_sent': True,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': self.request_diagnostics.get('effective_transport_mode'),
            'endpoint_family': 'backend-anon',
            'fallback_occurred': self.request_diagnostics.get('fallback_occurred', False),
            'url': 'https://chatgpt.com/backend-anon/f/conversation',
            'model': self.model_name,
            'thinking_mode': self.thinking_mode,
            'message_length': len(message),
            'has_image': False,
            'authorization_supplied': bool(self.authorization),
            'cookies_supplied': bool(self._supplied_cookies),
            'conversation_id_present_before_send': bool(self.data.get('conversation_id')),
        }

        conversation_request: requests.models.Response = self.session.post(
            self._endpoint_for('conversation'), json=conversation_data, timeout=(30, 300), stream=True
        )
        yield from self._consume_stream_response(conversation_request)
    
    def stream_question(self, message: str, image: str = None):
        if not image:
            yield from self.ask_question_with_file_stream(message)
        else:
            file_name = f"{str(uuid4())}.png"
            yield from self.ask_question_with_file_stream(message, file_name=file_name, file_b64=image, is_image=True)

    def ask_question(self, message: str, image: str = None) -> str:
        
        if not image:
            self.ask_question_with_file(message)
        else:
            file_name = f"{str(uuid4())}.png"
            self.ask_question_with_file(message, file_name=file_name, file_b64=image, is_image=True)
        
        return self.response

    def ask_question_with_file_stream(self, message: str, model: str | None = None, file_name: str = None, file_b64: str = None, is_image: bool = False):
        self._ensure_transport_ready('ask_question_with_file_stream')
        if self.request_diagnostics.get('effective_transport_mode') == 'authenticated':
            yield from self._authenticated_stream_initial(message, model=model, file_name=file_name, file_b64=file_b64, is_image=is_image)
            return

        model = model or self.model_name
        self._get_tokens()
        conduit_token: str = self.get_conduit()

        time_1: int = randint(6000, 9000)
        proof_token: str = Challenges.solve_pow(self.data["proofofwork"]["seed"], self.data["proofofwork"]["difficulty"], self.data["config"])
        turnstile_token: str = VM.get_turnstile(self.data["bytecode"], self.data["vm_token"], str(self.ip_info[:-1]))

        self._set_headers_for('conversation', extra={
            'oai-echo-logs': f'0,{time_1},1,{time_1 + randint(1000, 1200)}',
            'openai-sentinel-chat-requirements-token': self.data["token"],
            'openai-sentinel-proof-token': proof_token,
            'openai-sentinel-turnstile-token': turnstile_token,
            'x-conduit-token': conduit_token,
        })

        msg = {
            'id': str(uuid4()),
            'author': {'role': 'user'},
            'create_time': round(time(), 3),
            'metadata': {
                'selected_github_repos': [],
                'selected_all_github_repos': False,
                'selected_sources': [],
                'serialization_metadata': {'custom_symbol_offsets': []},
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
            attachment = {'id': file_id, 'size': file_size, 'name': file_name, 'mime_type': mime_type, 'source': 'local'}
            if is_image:
                attachment.update({'width': width, 'height': height})
            msg['metadata']['attachments'] = [attachment]

        if is_image:
            msg['content'] = {
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
            msg['content'] = {'content_type': 'text', 'parts': [message]}

        conversation_data = {
            'action': 'next',
            'messages': [msg],
            'parent_message_id': 'client-created-root',
            'model': model,
            'effort': self.thinking_mode,
            'timezone_offset_min': self.timezone_offset,
            'timezone': self.ip_info[5],
            'history_and_training_disabled': True,
            'conversation_mode': {'kind': 'primary_assistant'},
            'enable_message_followups': True,
            'system_hints': [],
            'supports_buffering': True,
            'supported_encodings': ['v1'],
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

        self._update_request_diagnostics(endpoint_family='backend-anon')
        self.last_request_summary = {
            'request_sent': True,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': self.request_diagnostics.get('effective_transport_mode'),
            'endpoint_family': 'backend-anon',
            'fallback_occurred': self.request_diagnostics.get('fallback_occurred', False),
            'url': 'https://chatgpt.com/backend-anon/f/conversation',
            'model': model,
            'thinking_mode': self.thinking_mode,
            'message_length': len(message),
            'has_image': is_image,
            'authorization_supplied': bool(self.authorization),
            'cookies_supplied': bool(self._supplied_cookies),
            'conversation_id_present_before_send': bool(self.data.get('conversation_id')),
        }

        conversation_request: requests.models.Response = self.session.post(
            self._endpoint_for('conversation'), json=conversation_data, timeout=(30, 300), stream=True
        )
        yield from self._consume_stream_response(conversation_request)

    def ask_question_with_file(self, message: str, model: str | None = None, file_name: str = None, file_b64: str = None, is_image: bool = False) -> str:
        self._ensure_transport_ready('ask_question_with_file')
        if self.request_diagnostics.get('effective_transport_mode') == 'authenticated':
            return self._authenticated_send_initial(message, model=model, file_name=file_name, file_b64=file_b64, is_image=is_image)

        model = model or self.model_name
        self._get_tokens()
        conduit_token: str = self.get_conduit()

        time_1: int = randint(6000, 9000)
        proof_token: str = Challenges.solve_pow(self.data["proofofwork"]["seed"], self.data["proofofwork"]["difficulty"], self.data["config"])
        turnstile_token: str = VM.get_turnstile(self.data["bytecode"], self.data["vm_token"], str(self.ip_info[:-1]))

        self._set_headers_for('conversation', extra={
            'oai-echo-logs': f'0,{time_1},1,{time_1 + randint(1000, 1200)}',
            'openai-sentinel-chat-requirements-token': self.data["token"],
            'openai-sentinel-proof-token': proof_token,
            'openai-sentinel-turnstile-token': turnstile_token,
            'x-conduit-token': conduit_token,
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

        self._update_request_diagnostics(endpoint_family='backend-anon')
        self.last_request_summary = {
            'request_sent': True,
            'selected_transport_mode': self.transport_mode,
            'effective_transport_mode': self.request_diagnostics.get('effective_transport_mode'),
            'endpoint_family': 'backend-anon',
            'fallback_occurred': self.request_diagnostics.get('fallback_occurred', False),
            'url': 'https://chatgpt.com/backend-anon/f/conversation',
            'model': model,
            'thinking_mode': self.thinking_mode,
            'message_length': len(message),
            'has_image': is_image,
            'authorization_supplied': bool(self.authorization),
            'cookies_supplied': bool(self._supplied_cookies),
            'conversation_id_present_before_send': bool(self.data.get('conversation_id')),
        }

        conversation_request: requests.models.Response = self.session.post(self._endpoint_for('conversation'), json=conversation_data, timeout=(30, 300))
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
        
        conversation_id, _ = self._apply_conversation_state_from_text(conversation_request.text)
        self.response = self._parse_event_stream(conversation_request.text)
        if not self.response and not conversation_id:
            preview = conversation_request.text[:300]
            raise RuntimeError(f"Conversation response did not contain a usable answer or conversation id. Preview: {preview}")
        return self.response
