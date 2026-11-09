"""Documentation models for the standard error response (P-3 format).

Used in route ``responses=`` declarations so Swagger shows the real error shape.
"""

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password.", "request_id": "3f2c..."}
            }
        }
    )

    error: ErrorDetail
