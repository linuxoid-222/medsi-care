from unittest.mock import patch
from datetime import datetime, timezone

from fastapi import HTTPException
import pytest

from app import main
from app.ai.gigachat import (
    FactExtractionValidationError, GigaChatConfigurationError, GigaChatRequestError,
)
from app.auth import UserContext
from app.schemas import CheckInCreate, DemoLoadRequest
from app.store import InMemoryStore


@pytest.mark.parametrize("failure", [
    GigaChatRequestError("synthetic timeout"),
    GigaChatRequestError("synthetic HTTP error", status_code=429),
    FactExtractionValidationError("synthetic invalid evidence"),
    GigaChatConfigurationError("synthetic missing configuration"),
])
def test_provider_failure_preserves_manual_monitoring_and_history(monkeypatch, failure):
    monkeypatch.setattr(main, "store", InMemoryStore())
    user = UserContext("demo-user", "user", "profile-demo")
    caregiver = UserContext("demo-caregiver", "caregiver", "profile-demo")
    main.load_demo_scenario(DemoLoadRequest(), user)
    check_in = main.create_check_in(
        "profile-demo", CheckInCreate(text="Сегодня чувствую слабость"), user,
    )
    with (
        patch.object(main.GigaChatSettings, "from_env", return_value=object()),
        patch.object(main, "GigaChatProvider") as provider,
    ):
        if isinstance(failure, GigaChatConfigurationError):
            provider.side_effect = failure
        else:
            provider.return_value.extract_facts.side_effect = failure
        with pytest.raises(HTTPException) as raised:
            main.extract_check_in_facts("profile-demo", check_in.id, user)
    assert raised.value.status_code == (503 if isinstance(failure, GigaChatConfigurationError) else 502)
    assert main.store.list_symptom_facts(check_in.id) == []
    assert main.store.list_monitoring_events("profile-demo") == []
    assert len(main.list_check_ins("profile-demo", user)) == 22
    assert len(main.list_observations("profile-demo", user)) == 63
    # Monitoring and caregiver read must never invoke the LLM provider.
    with patch.object(main, "GigaChatProvider", side_effect=AssertionError("LLM called by monitoring")):
        result = main.analyze_profile(
            "profile-demo", user, as_of=datetime(2026, 10, 21, 12, tzinfo=timezone.utc),
        )
        assert result.status.value == "attention"
        summary = main.caregiver_summary("profile-demo", caregiver)
    assert summary.events and summary.notifications
