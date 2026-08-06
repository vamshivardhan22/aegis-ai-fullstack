"""Simple in-memory rate limiting middleware for API hardening."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Bound request volume per client IP over a rolling window."""

    def __init__(self, app: Any, requests_per_minute: int = 120) -> None:
        """Initialize the middleware with a per-IP quota."""

        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Apply the rate limit and return 429 when exceeded."""

        if request.url.path == "/health":
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        events = self._requests[client]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.requests_per_minute:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded", "code": "RATE_LIMITED"})
        events.append(now)
        return await call_next(request)
