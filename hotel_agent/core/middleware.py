"""
Custom middleware for Hotel Voice Agent.
- RequestLoggingMiddleware: structured request/response logging
- RateLimitMiddleware: IP-based rate limiting with Redis
"""
import time
import json
import hashlib
import logging
from django.core.cache import cache
from django.http import JsonResponse
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("hotel_agent.middleware")


class RequestLoggingMiddleware:
    """Structured JSON request logging with timing."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.sensitive_paths = {"/api/v1/auth/token/", "/api/v1/auth/register/"}

    def __call__(self, request):
        start = time.monotonic()
        request._start_time = start

        response = self.get_response(request)

        duration_ms = (time.monotonic() - start) * 1000
        user_id = str(request.user.id) if request.user.is_authenticated else "anonymous"

        log_data = {
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "user_id": user_id,
            "ip": self._get_client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
        }

        if response.status_code >= 500:
            logger.error("request_error", extra=log_data)
        elif response.status_code >= 400:
            logger.warning("request_warning", extra=log_data)
        else:
            logger.info("request_ok", extra=log_data)

        response["X-Response-Time"] = f"{duration_ms:.2f}ms"
        return response

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


class RateLimitMiddleware(MiddlewareMixin):
    """
    Redis-backed sliding window rate limiter.
    Applied before DRF throttling for critical endpoints.
    """

    RULES = {
        "/api/v1/auth/token/": {"limit": 5, "window": 60},
        "/api/v1/auth/register/": {"limit": 3, "window": 300},
        "/api/v1/voice/": {"limit": 10, "window": 60},
    }
    BLOCK_DURATION = 300  # 5 minutes block after limit exceeded

    def process_request(self, request):
        if not getattr(settings, "RATELIMIT_ENABLE", True):
            return None

        rule = self._match_rule(request.path)
        if not rule:
            return None

        client_ip = self._get_client_ip(request)
        key = self._make_key(client_ip, request.path)
        block_key = f"{key}:blocked"

        # Check if currently blocked
        if cache.get(block_key):
            return JsonResponse(
                {"error": "Too many requests. Please try again later.", "code": "rate_limited"},
                status=429,
                headers={"Retry-After": str(self.BLOCK_DURATION)},
            )

        # Sliding window count
        count = cache.get(key, 0)
        if count >= rule["limit"]:
            cache.set(block_key, True, self.BLOCK_DURATION)
            logger.warning("rate_limit_blocked", extra={"ip": client_ip, "path": request.path})
            return JsonResponse(
                {"error": "Rate limit exceeded.", "code": "rate_limited"},
                status=429,
                headers={"Retry-After": str(self.BLOCK_DURATION)},
            )

        # Increment counter
        if count == 0:
            cache.set(key, 1, rule["window"])
        else:
            cache.incr(key)

        return None

    def _match_rule(self, path: str) -> dict | None:
        for pattern, rule in self.RULES.items():
            if path.startswith(pattern):
                return rule
        return None

    @staticmethod
    def _get_client_ip(request) -> str:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "unknown")

    @staticmethod
    def _make_key(ip: str, path: str) -> str:
        raw = f"rl:{ip}:{path}"
        return hashlib.sha256(raw.encode()).hexdigest()[:40]
