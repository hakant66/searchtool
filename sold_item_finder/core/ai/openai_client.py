from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Callable

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - import fallback for optional dependency
    OpenAI = None  # type: ignore[assignment]


class OpenAIClientError(Exception):
    pass


class OpenAIUnavailableError(OpenAIClientError):
    pass


class OpenAIRateLimitError(OpenAIClientError):
    pass


class OpenAITimeoutError(OpenAIClientError):
    pass


class OpenAIClient:
    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client: Any | None = None
        self.enabled = bool(self.api_key and OpenAI is not None)
        if self.enabled:
            self._client = OpenAI(api_key=self.api_key, timeout=timeout_s, max_retries=0)

    def get_text_embedding(self, text: str, model: str) -> list[float]:
        client = self._require_client()

        def _call() -> list[float]:
            response = client.embeddings.create(model=model, input=text)
            if not response.data:
                raise OpenAIClientError("OpenAI embeddings response is empty")
            return list(response.data[0].embedding)

        return self._with_retries(_call)

    def describe_image(self, image_path: str, model: str = "gpt-4o") -> str:
        client = self._require_client()
        image_file = Path(image_path)
        if not image_file.exists():
            raise OpenAIClientError(f"Image not found: {image_path}")
        mime = "image/jpeg"
        suffix = image_file.suffix.lower()
        if suffix == ".png":
            mime = "image/png"
        elif suffix == ".webp":
            mime = "image/webp"

        encoded = base64.b64encode(image_file.read_bytes()).decode("ascii")
        prompt = (
            "Describe this sold item image in concise plain text for search indexing. "
            "Include probable brand, product type, primary color, key visual attributes, "
            "and visible identifiers like SKU/size when present. "
            "Return one compact paragraph without markdown."
        )

        def _call() -> str:
            response = client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"},
                        ],
                    }
                ],
            )
            output = getattr(response, "output_text", "") or ""
            if not output.strip():
                raise OpenAIClientError("OpenAI image description response is empty")
            return " ".join(output.split())

        return self._with_retries(_call)

    def _require_client(self) -> Any:
        if OpenAI is None:
            raise OpenAIUnavailableError("openai package is not installed")
        if not self.api_key:
            raise OpenAIUnavailableError("OPENAI_API_KEY is not set")
        if self._client is None:
            raise OpenAIUnavailableError("OpenAI client is not initialized")
        return self._client

    def _with_retries(self, fn: Callable[[], Any]) -> Any:
        delay_s = 0.8
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                if "rate" in message and "limit" in message:
                    mapped = OpenAIRateLimitError(str(exc))
                elif "timeout" in message:
                    mapped = OpenAITimeoutError(str(exc))
                else:
                    mapped = OpenAIClientError(str(exc))
                if attempt >= self.max_retries:
                    raise mapped
                time.sleep(delay_s)
                delay_s *= 2
        raise OpenAIClientError(str(last_error) if last_error else "OpenAI request failed")
