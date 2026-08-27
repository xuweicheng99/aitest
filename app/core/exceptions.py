from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ModelProviderError(AppError):
    status_code = 502
    code = "model_provider_error"


class InvalidRequestError(AppError):
    status_code = 400
    code = "invalid_request"


class RunNotFoundError(AppError):
    status_code = 404
    code = "run_not_found"


class ArtifactNotFoundError(AppError):
    status_code = 404
    code = "artifact_not_found"
