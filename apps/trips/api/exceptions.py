"""One error envelope for the whole API: {"error": {"code", "message", "fields"?}}."""
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from ..domain.errors import DomainError


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.http_status)

    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, ValidationError):
        response.data = {"error": {"code": "validation_error", "message": "Some fields are invalid.", "fields": exc.detail}}
    else:
        detail = response.data.get("detail", "Request failed.") if isinstance(response.data, dict) else "Request failed."
        response.data = {"error": {"code": "request_failed", "message": str(detail)}}
    return response
