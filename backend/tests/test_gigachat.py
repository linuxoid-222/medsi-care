import json
from unittest import TestCase

import httpx

from app.ai.gigachat import (
    FactExtractionPayload,
    FactExtractionValidationError,
    GigaChatProvider,
    GigaChatRequestError,
    GigaChatSettings,
)


class GigaChatAdapterTests(TestCase):
    def _provider(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return GigaChatProvider(
            GigaChatSettings(
                base_url="https://api.giga.chat",
                oauth_url="https://auth.example.test/oauth",
                auth_key="synthetic-auth-key",
                scope="GIGACHAT_API_PERS",
                model="GigaChat-2",
            ),
            client=client,
        )

    def test_extracts_and_validates_structured_facts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "auth.example.test":
                self.assertEqual(request.headers["RqUID"].count("-"), 4)
                return httpx.Response(
                    200,
                    json={"access_token": "synthetic-token", "expires_at": 4102444800},
                )
            body = json.loads(request.content)
            self.assertEqual(body["model_options"]["response_format"]["type"], "json_schema")
            content = json.dumps(
                {"facts": [{
                    "category": "weakness",
                    "polarity": "present",
                    "evidence": "чувствую слабость",
                }]},
                ensure_ascii=False,
            )
            return httpx.Response(200, json={"messages": [{"content": [{"text": content}]}]})

        provider = self._provider(handler)
        facts = provider.extract_facts("Сегодня чувствую слабость")
        provider.close()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].category, "weakness")
        self.assertFalse(facts[0].confirmed)

    def test_rejects_evidence_not_present_in_source(self) -> None:
        payload = FactExtractionPayload.model_validate({
            "facts": [{
                "category": "weakness",
                "polarity": "present",
                "evidence": "выдуманная слабость",
            }]
        })
        provider = self._provider(lambda _: httpx.Response(500))
        with self.assertRaises(FactExtractionValidationError):
            from app.ai.gigachat import validate_fact_payload

            validate_fact_payload("Сегодня всё хорошо", payload)
        provider.close()

    def test_propagates_provider_http_error_without_creating_facts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"message": "rate limited"})

        provider = self._provider(handler)
        with self.assertRaises(GigaChatRequestError) as raised:
            provider.extract_facts("Сегодня чувствую слабость")
        provider.close()
        self.assertEqual(raised.exception.status_code, 429)

    def test_timeout_is_a_controlled_provider_failure(self) -> None:
        for stage in ("oauth", "completion"):
            with self.subTest(stage=stage):
                def handler(request):
                    if request.url.host == "auth.example.test" and stage == "completion":
                        return httpx.Response(200, json={
                            "access_token": "synthetic-token", "expires_at": 4102444800,
                        })
                    raise httpx.ReadTimeout("synthetic timeout", request=request)

                provider = self._provider(handler)
                try:
                    with self.assertRaises(GigaChatRequestError):
                        provider.extract_facts("Сегодня чувствую слабость")
                finally:
                    provider.close()

    def test_blank_evidence_and_invalid_json_are_rejected(self) -> None:
        for content in ("not json", json.dumps({"facts": [{
            "category": "weakness", "polarity": "present", "evidence": "   ",
        }]})):
            def handler(request):
                if request.url.host == "auth.example.test":
                    return httpx.Response(200, json={
                        "access_token": "synthetic-token", "expires_at": 4102444800,
                    })
                return httpx.Response(200, json={"messages": [{"content": [{"text": content}]}]})

            provider = self._provider(handler)
            try:
                with self.assertRaises(FactExtractionValidationError):
                    provider.extract_facts("Сегодня чувствую слабость")
            finally:
                provider.close()

    def test_provider_error_cannot_echo_credentials_in_exception(self) -> None:
        provider = self._provider(lambda _: httpx.Response(
            401, json={"message": "synthetic-auth-key synthetic-token"},
        ))
        try:
            with self.assertRaises(GigaChatRequestError) as raised:
                provider.extract_facts("Сегодня чувствую слабость")
            self.assertNotIn("synthetic-auth-key", str(raised.exception))
            self.assertNotIn("synthetic-token", str(raised.exception))
            self.assertNotIn("synthetic-auth-key", repr(provider.settings))
        finally:
            provider.close()
