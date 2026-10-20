"""Bounded per-process abuse protection for the single-instance local API."""
import time
from collections import OrderedDict
from threading import Lock

from fastapi.responses import JSONResponse

from app.config.settings import get_settings

_attempts = OrderedDict()
_lock = Lock()


async def protect_auth(request, call_next):
    path = request.url.path
    if not path.startswith("/api/v1/auth"):
        return await call_next(request)
    settings = get_settings()
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        # Never trust X-Forwarded-For supplied by a browser. Configure uvicorn's
        # trusted proxy list explicitly if the API is placed behind a proxy.
        key = (request.client.host if request.client else "unknown", path)
        limit = 10 if path.endswith(("/login", "/password/recover", "/forgot-password")) else 60
        timestamp = time.monotonic()
        with _lock:
            start, count = _attempts.get(key, (timestamp, 0))
            if timestamp - start >= 60:
                start, count = timestamp, 0
            _attempts[key] = (start, count + 1)
            _attempts.move_to_end(key)
            while len(_attempts) > 10000:
                _attempts.popitem(last=False)
        if count >= limit:
            return JSONResponse({"detail": "Too many attempts; try again shortly"}, status_code=429,
                                headers={"Retry-After": "60", "Cache-Control": "no-store"})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
