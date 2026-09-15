"""OpenAI-compatible external provider client (keys are request-only)."""
from __future__ import annotations

from urllib.parse import urlparse
import httpx


class ExternalAIError(Exception):
    """An external-provider failure with a safe, user-facing description."""

    def __init__(self, safe_message: str):
        self.safe_message = safe_message
        super().__init__(safe_message)


def _endpoint(base_url: str | None) -> str:
    base = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ExternalAIError("The provider URL must be a valid HTTP(S) URL.")
    # Accept either an API root, a /v1 root, or a full OpenAI-compatible
    # chat-completions endpoint.  This prevents accidental /v1/v1 paths.
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/chat/completions"


async def generate(*, api_key: str, model: str, base_url: str | None, system_prompt: str, user_prompt: str) -> str:
    if not api_key or not api_key.strip():
        raise ExternalAIError("An API key is required for the external provider.")
    if not model or not model.strip():
        raise ExternalAIError("A model is required for the external provider.")
    try:
        # Larger reasoning models can legitimately take longer than one minute
        # to produce lecture notes.  This is a normal request timeout, not a
        # background job, and remains bounded.
        timeout = httpx.Timeout(180.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _endpoint(base_url),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                # Keep the body to the OpenAI-compatible common subset.
                # Some hosted reasoning models reject optional sampling knobs.
                ], "stream": False},
            )
    except httpx.TimeoutException as exc:
        raise ExternalAIError("External provider timed out.") from exc
    except httpx.RequestError as exc:
        raise ExternalAIError("External provider is unavailable.") from exc

    if response.status_code in {401, 403}:
        raise ExternalAIError("External provider rejected the API key.")
    if response.status_code == 429:
        raise ExternalAIError("External provider rate limit reached.")
    if response.status_code == 400:
        raise ExternalAIError("External provider rejected the request. Check the model name and provider URL.")
    if response.status_code == 404:
        raise ExternalAIError("External provider could not find that model or endpoint. Check the model name and base URL.")
    if response.status_code == 413:
        raise ExternalAIError("The transcript is too large for the external provider.")
    if response.status_code == 422:
        raise ExternalAIError("External provider rejected the request format or model.")
    if response.status_code >= 400:
        raise ExternalAIError("External provider could not complete the request.")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ExternalAIError("External provider returned an invalid response.") from exc
    # Most chat-completions APIs return a string.  A few compatible APIs use
    # content parts; accept their text parts without rendering any raw HTML.
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ExternalAIError("External provider returned an empty response.")
    return content.strip()


async def test_connection(*, api_key: str, model: str, base_url: str | None) -> None:
    await validate_model(api_key=api_key, model=model, base_url=base_url)
    await generate(api_key=api_key, model=model, base_url=base_url,
                   system_prompt="You are a connection test. Reply with OK.", user_prompt="Reply with OK.")


async def validate_model(*, api_key: str, model: str, base_url: str | None) -> None:
    """Check credentials and model access without sending lecture content."""
    if not api_key or not api_key.strip() or not model or not model.strip():
        raise ExternalAIError("API key and model are required.")
    endpoint = _endpoint(base_url)
    models_url = endpoint.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=15.0)) as client:
            response = await client.get(models_url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.TimeoutException as exc:
        raise ExternalAIError("External provider timed out while checking model access.") from exc
    except httpx.RequestError as exc:
        raise ExternalAIError("External provider is unavailable.") from exc
    if response.status_code in {401, 403}:
        raise ExternalAIError("External provider rejected the API key.")
    if response.status_code >= 400:
        # Not every compatible provider exposes /models. Generation remains
        # the definitive check for those providers.
        return
    try:
        model_ids = {item.get("id") for item in response.json().get("data", []) if isinstance(item, dict)}
    except (ValueError, AttributeError):
        return
    if model_ids and model not in model_ids:
        raise ExternalAIError(f"The model '{model}' is not available for this API key. Use an exact model ID from the provider.")
