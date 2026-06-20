from __future__ import annotations

import unittest

from app.ai import llm, prompts, response_preferences


class AiResponsePreferencesTests(unittest.TestCase):
    def test_japanese_locale_is_enabled(self) -> None:
        preferences = response_preferences.build_response_preferences(
            {
                "ui_context": {
                    "settings": {
                        "response_locale": "ja-JP",
                        "response_language": "Japanese",
                        "theme": "dark",
                    }
                }
            }
        )

        self.assertEqual(preferences["requested_locale"], "ja-JP")
        self.assertEqual(preferences["effective_locale"], "ja-JP")
        self.assertFalse(preferences["reserved_locale"])
        self.assertEqual(preferences["theme"], "dark")
        self.assertEqual(preferences["language"], "Japanese")
        self.assertIn("Japanese", preferences["language_instruction"])

    def test_system_prompt_uses_english_instruction(self) -> None:
        system_prompt = prompts.build_system_prompt(
            "technical_swing",
            response_preferences={
                "effective_locale": "en-US",
                "language_instruction": "Write all human-readable output strings in English.",
            },
        )

        self.assertIn("Write all human-readable output strings in English.", system_prompt)
        self.assertNotIn("Write every report string value in Traditional Chinese.", system_prompt)

    def test_report_payload_includes_response_preferences_and_english_rule(self) -> None:
        payload = llm.build_responses_payload(
            {
                "kind": "stock_brief",
                "response_preferences": {
                    "effective_locale": "en-US",
                    "language_instruction": "Write all human-readable output strings in English.",
                },
                "prompt": {
                    "system": prompts.build_system_prompt(
                        "technical_swing",
                        response_preferences={
                            "effective_locale": "en-US",
                            "language_instruction": "Write all human-readable output strings in English.",
                        },
                    )
                },
                "summary": {},
                "data": {},
                "missing": [],
                "warnings": [],
            }
        )

        joined_input = "\n".join(
            content["text"]
            for message in payload["input"]
            for content in message["content"]
            if content.get("type") == "input_text"
        )
        self.assertIn("Write all human-readable output strings in English.", joined_input)
        self.assertIn('"effective_locale": "en-US"', joined_input)

    def test_report_payload_includes_response_preferences_and_japanese_rule(self) -> None:
        preferences = response_preferences.build_response_preferences(
            {"ui_context": {"settings": {"response_locale": "ja-JP"}}}
        )
        payload = llm.build_responses_payload(
            {
                "kind": "stock_brief",
                "response_preferences": preferences,
                "prompt": {
                    "system": prompts.build_system_prompt(
                        "technical_swing",
                        response_preferences=preferences,
                    )
                },
                "summary": {},
                "data": {},
                "missing": [],
                "warnings": [],
            }
        )

        joined_input = "\n".join(
            content["text"]
            for message in payload["input"]
            for content in message["content"]
            if content.get("type") == "input_text"
        )
        self.assertIn("Write all human-readable output strings in Japanese.", joined_input)
        self.assertIn('"effective_locale": "ja-JP"', joined_input)


if __name__ == "__main__":
    unittest.main()
