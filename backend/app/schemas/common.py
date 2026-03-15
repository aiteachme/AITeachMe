"""通用 Schema — ErrorResponse、HealthResponse"""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    error_code: str


class HealthResponse(BaseModel):
    status: str = "ok"
