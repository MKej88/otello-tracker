from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Det stabile, offentlige svaret fra helsesjekken."""

    status: str
    service: str
    environment: str
    version: str

    model_config = ConfigDict(extra="forbid")
