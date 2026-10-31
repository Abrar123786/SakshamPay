from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "healthy", "application": "SakshamPay", "version": "1.0.0"}}
    )

    status: Literal["healthy"]
    application: str
    version: str
