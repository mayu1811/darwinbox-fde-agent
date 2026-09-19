"""Structured application exceptions mapped to HTTP responses in main.py."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class InvalidStateError(AppError):
    status_code = 409
    code = "invalid_state"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"
