from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.ai.schemas import AiAskV4Request
from app.main import app


class AiPublicV4ContractTests(unittest.TestCase):
    def test_public_request_defaults_to_v4_and_rejects_legacy_versions(self) -> None:
        request = AiAskV4Request(question="2330 怎麼看")

        self.assertEqual(request.contract_version, "omi.decision.v4")
        for contract_version in ("omi.decision.v3", "omi.ai.ask.v2"):
            with self.subTest(contract_version=contract_version):
                with self.assertRaises(ValidationError):
                    AiAskV4Request(
                        question="2330 怎麼看",
                        contract_version=contract_version,
                    )

    def test_openapi_exposes_only_v4_request_and_response_models(self) -> None:
        schema = app.openapi()
        components = schema["components"]["schemas"]

        request_schema = components["AiAskV4Request"]["properties"][
            "contract_version"
        ]
        response_schema = components["AiDecisionEnvelopeV4"]["properties"][
            "contract_version"
        ]
        ask_operation = schema["paths"]["/api/ai/ask"]["post"]
        stream_operation = schema["paths"]["/api/ai/ask/stream"]["post"]

        self.assertEqual(request_schema["const"], "omi.decision.v4")
        self.assertEqual(response_schema["const"], "omi.decision.v4")
        self.assertEqual(
            ask_operation["requestBody"]["content"]["application/json"]["schema"][
                "$ref"
            ],
            "#/components/schemas/AiAskV4Request",
        )
        self.assertEqual(
            stream_operation["requestBody"]["content"]["application/json"][
                "schema"
            ]["$ref"],
            "#/components/schemas/AiAskV4Request",
        )
        self.assertEqual(
            ask_operation["responses"]["200"]["content"]["application/json"][
                "schema"
            ]["$ref"],
            "#/components/schemas/AiDecisionEnvelopeV4",
        )
