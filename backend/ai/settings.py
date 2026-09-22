"""Local provider preferences; secrets live only in the OS credential vault."""
from __future__ import annotations
import json
from pathlib import Path

SERVICE = "audio-notes"
ACCOUNT = "external-api-key"
DEFAULT = {"model": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1"}

def _preferences_file() -> Path:
    path = Path(__file__).resolve().parents[2] / "data" / "provider_preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def get_preferences() -> dict:
    values = DEFAULT.copy()
    try: values.update({k: v for k, v in json.loads(_preferences_file().read_text(encoding="utf-8")).items() if k in DEFAULT and isinstance(v, str)})
    except (FileNotFoundError, ValueError): pass
    try:
        import keyring
        values["has_api_key"] = bool(keyring.get_password(SERVICE, ACCOUNT))
        values["key_storage"] = "os_keychain"
    except Exception:
        values["has_api_key"] = False; values["key_storage"] = "unavailable"
    return values

def save_preferences(*, model: str | None = None, base_url: str | None = None, api_key: str | None = None) -> dict:
    values = get_preferences()
    if model is not None: values["model"] = model.strip()
    if base_url is not None: values["base_url"] = base_url.strip()
    _preferences_file().write_text(json.dumps({k: values[k] for k in DEFAULT}, indent=2), encoding="utf-8")
    if api_key:
        try:
            import keyring
            keyring.set_password(SERVICE, ACCOUNT, api_key.strip())
        except Exception as exc: raise RuntimeError("Secure OS credential storage is unavailable. Install keyring and configure your system keychain.") from exc
    return get_preferences()

def get_api_key(request_key: str | None) -> str | None:
    if request_key and request_key.strip(): return request_key.strip()
    try:
        import keyring
        return keyring.get_password(SERVICE, ACCOUNT)
    except Exception: return None
