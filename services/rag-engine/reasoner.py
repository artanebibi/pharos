from __future__ import annotations

from abc import ABC, abstractmethod

from config import Settings


class Reasoner(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        ...


class GeminiReasoner(Reasoner):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        from google import genai
        from google.genai import types

        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Add it to the repo-root .env")

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""


class OllamaReasoner(Reasoner):
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def generate(self, prompt: str) -> str:
        raise NotImplementedError("Ollama backend not yet configured")


def build_reasoner(settings: Settings) -> Reasoner:
    if settings.reasoner_backend == "gemini":
        return GeminiReasoner(
            api_key=settings.gemini_api_key or "", model=settings.gemini_model
        )
    if settings.reasoner_backend == "ollama":
        return OllamaReasoner()
    raise ValueError(
        f"Unknown REASONER_BACKEND={settings.reasoner_backend!r} (expected 'gemini' or 'ollama')"
    )
