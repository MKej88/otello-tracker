import pytest
from pydantic import ValidationError

from app.api_models import HealthResponse


def test_health_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HealthResponse(
            status="ok",
            service="otello-api",
            environment="test",
            version="1.0.0",
            unexpected="should not leak",
        )
