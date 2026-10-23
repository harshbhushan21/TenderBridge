"""Domain errors with HTTP mapping."""
from __future__ import annotations


class TenderBridgeError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, "details": self.details}


class NotFoundError(TenderBridgeError):
    status_code = 404
    code = "not_found"


class ValidationFailed(TenderBridgeError):
    status_code = 422
    code = "validation_failed"


class ConflictError(TenderBridgeError):
    status_code = 409
    code = "conflict"


class InvalidStateError(TenderBridgeError):
    """Operation not allowed in the current workflow state (e.g. Analyze before ready)."""
    status_code = 409
    code = "invalid_state"


class FileRejected(TenderBridgeError):
    status_code = 400
    code = "file_rejected"


class PermissionDenied(TenderBridgeError):
    status_code = 403
    code = "permission_denied"


class BudgetExceeded(TenderBridgeError):
    status_code = 429
    code = "budget_exceeded"


class LLMOutputError(TenderBridgeError):
    """Structured output invalid even after schema-repair retry."""
    status_code = 502
    code = "llm_output_error"


class ToolError(TenderBridgeError):
    status_code = 500
    code = "tool_error"


class ConfigError(TenderBridgeError):
    status_code = 500
    code = "config_error"
