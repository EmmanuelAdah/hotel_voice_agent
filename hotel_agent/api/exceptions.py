"""Custom DRF exception handler for consistent error responses."""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger("hotel_agent.api.exceptions")


def custom_exception_handler(exc, context):
    """
    Returns consistent error envelope:
    {
        "error": "Human readable message",
        "code": "machine_readable_code",
        "details": {...}  # optional field-level errors
    }
    """
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception - log and return 500
        logger.exception(
            "unhandled_exception",
            extra={"view": str(context.get("view")), "error": str(exc)},
        )
        return Response(
            {"error": "An internal server error occurred.", "code": "internal_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Normalize DRF error responses
    error_data = response.data
    normalized = {
        "error": _extract_message(error_data),
        "code": _extract_code(error_data, response.status_code),
    }

    # Include field-level validation errors
    if isinstance(error_data, dict) and any(
        k not in ("detail", "code", "non_field_errors") for k in error_data
    ):
        normalized["details"] = {
            k: v if isinstance(v, list) else [v]
            for k, v in error_data.items()
            if k not in ("detail", "code")
        }

    response.data = normalized
    return response


def _extract_message(error_data) -> str:
    if isinstance(error_data, dict):
        detail = error_data.get("detail", "")
        if detail:
            return str(detail)
        non_field = error_data.get("non_field_errors", [])
        if non_field:
            return str(non_field[0])
        # First field error
        for key, val in error_data.items():
            if key not in ("code",):
                msg = val[0] if isinstance(val, list) else str(val)
                return f"{key}: {msg}"
    return str(error_data)


def _extract_code(error_data, http_status: int) -> str:
    if isinstance(error_data, dict):
        if "code" in error_data:
            return str(error_data["code"])
        detail = error_data.get("detail")
        if hasattr(detail, "code"):
            return detail.code
    codes = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        429: "rate_limited",
        500: "internal_error",
    }
    return codes.get(http_status, "error")
