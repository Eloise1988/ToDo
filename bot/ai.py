from __future__ import annotations

import logging

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


logger = logging.getLogger(__name__)


class AICoach:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self.enabled = bool(api_key) and OpenAI is not None
        self.client = OpenAI(api_key=api_key) if self.enabled else None  # type: ignore[arg-type]

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.enabled or self.client is None:
            return ""

        # Prefer the Responses API and fall back to Chat Completions for compatibility.
        try:
            response = self.client.responses.create(
                model=self.model,
                temperature=0.4,
                input=[
                    {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
                ],
            )
            text = getattr(response, "output_text", "")
            if text and text.strip():
                return text.strip()
        except Exception as exc:
            logger.warning("Responses API failed, trying chat completions fallback: %s", exc)

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                temperature=0.4,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = completion.choices[0].message.content
            return (content or "").strip()
        except Exception as exc:
            logger.error("OpenAI request failed: %s", exc)
            return ""
