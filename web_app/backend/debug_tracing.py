"""
Structured debug tracing when BACKEND_DEBUG or DEV_MODE is set (1, true, yes, on).

DEV_MODE also enables tracing so local dev matches expectations when skipping auth.
Logs to logger "nebula.debug" (stderr by default): HTTP outbound calls,
AWS API calls, per-request HTTP timing, and request start (before handler).

Optional per-call Python tracing: BACKEND_DEBUG_TRACE_PYTHON=1 only logs call/return
for main.py, graph.py, and persistence.py in this folder (exact path match — ignores
.aws-sam/build and any other trees under the backend directory).

Low-level http.client logging is opt-in (BACKEND_DEBUG_HTTP_CLIENT=1); it is extremely
noisy because urllib3 and many clients use HTTPConnection for almost every byte.
"""
from __future__ import annotations

import http.client
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_logger = logging.getLogger("nebula.debug")

# Real path to this package directory (only profile code under here)
_BACKEND_ROOT = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))

def _canonical_file(path: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return os.path.normcase(path)


# sys.setprofile may only record these exact app modules (not .aws-sam, venv, etc.)
_PROFILE_PY_FILES = ("main.py", "graph.py", "persistence.py")
_PROFILE_PATHS = frozenset(
    _canonical_file(os.path.join(_BACKEND_ROOT, name)) for name in _PROFILE_PY_FILES
)

_installed = False
_python_profile_enabled = False
_profile_depth = threading.local()


def _env_flag(name: str) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def is_backend_debug() -> bool:
    return _env_flag("BACKEND_DEBUG") or _env_flag("DEV_MODE")


def is_python_call_tracing() -> bool:
    return _env_flag("BACKEND_DEBUG_TRACE_PYTHON")


def is_http_client_tracing() -> bool:
    return _env_flag("BACKEND_DEBUG_HTTP_CLIENT")


def _log(msg: str, *args: Any) -> None:
    _logger.info(msg, *args)


def _patch_http_client() -> None:
    _orig_request = http.client.HTTPConnection.request
    _orig_getresponse = http.client.HTTPConnection.getresponse

    def request(
        self,
        method,
        url,
        body=None,
        headers=None,
        *,
        encode_chunked=False,
    ):
        self._nebula_http_t0 = time.perf_counter()
        self._nebula_http_method = method
        self._nebula_http_path = url
        return _orig_request(
            self, method, url, body=body, headers=headers, encode_chunked=encode_chunked
        )

    def getresponse(self):
        resp = _orig_getresponse(self)
        t0 = getattr(self, "_nebula_http_t0", None)
        dt_ms = (time.perf_counter() - t0) * 1000 if t0 is not None else -1.0
        host = getattr(self, "host", "?")
        method = getattr(self, "_nebula_http_method", "?")
        path = getattr(self, "_nebula_http_path", "?")
        status = getattr(resp, "status", "?")
        _log(
            "[network] http.client %s %s%s status=%s duration_ms=%.2f",
            method,
            host,
            path if str(path).startswith("/") else f"/{path}",
            status,
            dt_ms,
        )
        return resp

    http.client.HTTPConnection.request = request  # type: ignore[method-assign]
    http.client.HTTPConnection.getresponse = getresponse  # type: ignore[method-assign]


_httpx_tls = threading.local()


def _patch_httpx() -> None:
    try:
        import httpx
    except ImportError:
        return

    _orig_client_init = httpx.Client.__init__
    _orig_async_init = httpx.AsyncClient.__init__

    def _merge_hooks(
        kwargs: dict, request_hook: Callable, response_hook: Callable
    ) -> None:
        eh = kwargs.get("event_hooks")
        if eh is None:
            eh = {}
        if not isinstance(eh, dict):
            return
        req = list(eh.get("request") or [])
        resp = list(eh.get("response") or [])
        req.append(request_hook)
        resp.append(response_hook)
        eh = {**eh, "request": req, "response": resp}
        kwargs["event_hooks"] = eh

    def _mark_request_start(request: Any) -> None:
        if not hasattr(_httpx_tls, "starts"):
            _httpx_tls.starts = {}
        _httpx_tls.starts[id(request)] = time.perf_counter()
        ext = getattr(request, "extensions", None)
        if isinstance(ext, dict):
            try:
                ext["nebula_debug_t0"] = _httpx_tls.starts[id(request)]
            except Exception:
                pass

    def _request_start_time(request: Any) -> Optional[float]:
        ext = getattr(request, "extensions", None)
        if isinstance(ext, dict):
            t = ext.get("nebula_debug_t0")
            if t is not None:
                starts = getattr(_httpx_tls, "starts", None)
                if starts:
                    starts.pop(id(request), None)
                return float(t)
        starts = getattr(_httpx_tls, "starts", None)
        if not starts:
            return None
        return starts.pop(id(request), None)

    def _req_hook(request: Any) -> Any:
        _mark_request_start(request)
        try:
            u = str(request.url)
        except Exception:
            u = "?"
        _log("[network] httpx request %s %s", request.method, u)
        return request

    def _resp_hook(response: Any) -> Any:
        req = response.request
        t0 = _request_start_time(req)
        dt_ms = (time.perf_counter() - t0) * 1000 if t0 is not None else -1.0
        try:
            u = str(req.url)
        except Exception:
            u = "?"
        _log(
            "[network] httpx response %s %s status=%s duration_ms=%.2f",
            req.method,
            u,
            response.status_code,
            dt_ms,
        )
        return response

    def client_init(self, *a: Any, **kw: Any) -> None:
        _merge_hooks(kw, _req_hook, _resp_hook)
        _orig_client_init(self, *a, **kw)

    async def _async_req_hook(request: Any) -> Any:
        return _req_hook(request)

    async def _async_resp_hook(response: Any) -> Any:
        return _resp_hook(response)

    def async_client_init(self, *a: Any, **kw: Any) -> None:
        eh = kw.get("event_hooks")
        if eh is None:
            eh = {}
        if not isinstance(eh, dict):
            _orig_async_init(self, *a, **kw)
            return
        req = list(eh.get("request") or [])
        resp = list(eh.get("response") or [])
        req.append(_async_req_hook)
        resp.append(_async_resp_hook)
        kw["event_hooks"] = {**eh, "request": req, "response": resp}
        _orig_async_init(self, *a, **kw)

    httpx.Client.__init__ = client_init  # type: ignore[method-assign]
    httpx.AsyncClient.__init__ = async_client_init  # type: ignore[method-assign]


def _patch_botocore() -> None:
    try:
        import botocore.client
    except ImportError:
        return

    _orig = botocore.client.BaseClient._make_api_call

    def _wrapped(self: Any, operation_name: str, api_params: Any, *args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return _orig(self, operation_name, api_params, *args, **kwargs)
        finally:
            svc = self._service_model.service_name
            dt_ms = (time.perf_counter() - t0) * 1000
            _log(
                "[network] boto3 %s.%s duration_ms=%.2f",
                svc,
                operation_name,
                dt_ms,
            )

    botocore.client.BaseClient._make_api_call = _wrapped  # type: ignore[method-assign]


def _frame_qname(code: Any) -> str:
    return getattr(code, "co_qualname", code.co_name)


def _python_profile(frame: Any, event: str, arg: Any) -> None:
    if event not in ("call", "return"):
        return
    path = _canonical_file(frame.f_code.co_filename)
    if path not in _PROFILE_PATHS:
        return

    name = _frame_qname(frame.f_code)
    if event == "call":
        d = getattr(_profile_depth, "d", 0)
        _log("%s[py] call %s", "  " * d, name)
        _profile_depth.d = d + 1
    else:
        d = getattr(_profile_depth, "d", 0)
        if d <= 0:
            return
        _profile_depth.d = d - 1
        _log("%s[py] return %s", "  " * _profile_depth.d, name)


class DebugRequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        t0 = time.perf_counter()
        if request.method != "OPTIONS":
            _log("[timing] %s %s -> handler (started)", request.method, request.url.path)
        response = await call_next(request)
        dt_ms = (time.perf_counter() - t0) * 1000
        _log(
            "[timing] %s %s status=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            dt_ms,
        )
        return response


def enable_debug_tracing() -> None:
    global _installed, _python_profile_enabled
    if _installed:
        return
    _installed = True

    if not logging.getLogger("nebula.debug").handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(h)
        _logger.setLevel(logging.DEBUG)

    _log(
        "Backend debug tracing enabled (BACKEND_DEBUG or DEV_MODE): "
        "boto3, httpx, request timing"
    )
    if is_http_client_tracing():
        _patch_http_client()
        _log("BACKEND_DEBUG_HTTP_CLIENT: http.client request/response logging enabled")
    _patch_httpx()
    _patch_botocore()
    if is_python_call_tracing():
        sys.setprofile(_python_profile)
        _python_profile_enabled = True
        _log(
            "BACKEND_DEBUG_TRACE_PYTHON: call/return for %s only",
            ", ".join(_PROFILE_PY_FILES),
        )
    else:
        _log(
            "Python call tracing off (set BACKEND_DEBUG_TRACE_PYTHON=1 to enable)"
        )


def disable_debug_tracing() -> None:
    global _installed, _python_profile_enabled
    if not _installed:
        return
    if _python_profile_enabled:
        sys.setprofile(None)
        _python_profile_enabled = False
    _installed = False
