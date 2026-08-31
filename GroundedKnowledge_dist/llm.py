"""LLM client for the Salesforce eng-ai LiteLLM gateway (Anthropic Messages API).

Auth has two modes (settings `auth_mode`): "devbar" mints a short-lived virtual
key on demand via the devbar helper (never hardcoded); "manual" uses the API key
stored in settings, for machines without devbar. The gateway speaks the Anthropic
Messages format at POST /v1/messages with an x-api-key header (LiteLLM).
"""
import os
import subprocess
import urllib.request
import urllib.error
import json

import settings

DEVBAR = "/Applications/devbar.app/Contents/MacOS/devbar"


def devbar_available():
    return os.path.exists(DEVBAR)


def _mint_via_devbar():
    if not devbar_available():
        raise RuntimeError("devbar is not installed; switch to a manual API key in Settings")
    key = subprocess.run(
        [DEVBAR, "auth", "claude"], capture_output=True, text=True, timeout=30
    ).stdout.strip()
    if not key.startswith("sk-"):
        raise RuntimeError(f"devbar did not return an sk- key (got {key[:12]!r})")
    return key


def mint_key():
    """Return the gateway key per the configured auth mode."""
    if settings.get("auth_mode") == "manual":
        key = settings.get("api_key").strip()
        if not key:
            raise RuntimeError("no API key set; add one in Settings or switch to devbar")
        return key
    return _mint_via_devbar()


def complete(system, messages, model=None, max_tokens=None):
    """Call the gateway once and return the assistant's text.

    `messages` is a list of {"role","content"} in Anthropic format.
    Gateway URL, model, and max_tokens resolve from settings unless overridden.
    """
    base_url = settings.get("gateway_url").rstrip("/")
    body = json.dumps(
        {
            "model": model or settings.get("model"),
            "max_tokens": max_tokens or settings.get("max_tokens"),
            "system": system,
            "messages": messages,
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/v1/messages",
        data=body,
        headers={
            "x-api-key": mint_key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"gateway {e.code}: {detail}") from None
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()
