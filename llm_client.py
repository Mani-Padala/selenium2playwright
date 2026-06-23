"""
llm_client.py — Unified LLM client supporting multiple providers.

Supported providers:
  - claude   : Anthropic Claude (paid)
  - gemini   : Google Gemini (free tier available)
  - groq     : Groq (free tier available)

Usage:
    Set LLM_PROVIDER environment variable to switch providers:
        set LLM_PROVIDER=gemini
        set GEMINI_API_KEY=your_key_here

    Or pass --provider and --key flags to agent.py
"""

import time
import re
import requests

# ── Provider configs ───────────────────────────────────────────────────────────

PROVIDERS = {
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "default_model": "gemini-1.5-flash",
        "env_key": "GEMINI_API_KEY",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "llama-3.1-70b-versatile",
        "env_key": "GROQ_API_KEY",
    },
}


def call_llm(
    system: str,
    user: str,
    api_key: str,
    provider: str = "claude",
    max_tokens: int = 4000,
) -> str:
    """
    Call the specified LLM provider and return the text response.
    Retries up to 3 times on network errors.

    Args:
        system:     System prompt.
        user:       User message.
        api_key:    API key for the provider.
        provider:   One of 'claude', 'gemini', 'groq'.
        max_tokens: Maximum tokens in the response.

    Returns:
        Text response from the LLM.
    """
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {list(PROVIDERS.keys())}")

    if provider == "claude":
        return _call_claude(system, user, api_key, max_tokens)
    elif provider == "gemini":
        return _call_gemini(system, user, api_key, max_tokens)
    elif provider == "groq":
        return _call_groq(system, user, api_key, max_tokens)


# ── Claude ────────────────────────────────────────────────────────────────────

def _call_claude(system: str, user: str, api_key: str, max_tokens: int) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    return _post_with_retry(url, headers=headers, json=payload, extractor=_extract_claude)


def _extract_claude(data: dict) -> str:
    blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    if not blocks:
        raise RuntimeError(f"No text in Claude response: {data}")
    return "\n".join(blocks)


# ── Gemini ────────────────────────────────────────────────────────────────────

def _call_gemini(system: str, user: str, api_key: str, max_tokens: int) -> str:
    model = "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"content-type": "application/json"}
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    return _post_with_retry(url, headers=headers, json=payload, extractor=_extract_gemini)


def _extract_gemini(data: dict) -> str:
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"No candidates in Gemini response: {data}")
        parts = candidates[0]["content"]["parts"]
        return "\n".join(p["text"] for p in parts if "text" in p)
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response structure: {data}") from e


# ── Groq ──────────────────────────────────────────────────────────────────────

def _call_groq(system: str, user: str, api_key: str, max_tokens: int) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    return _post_with_retry(url, headers=headers, json=payload, extractor=_extract_groq)


def _extract_groq(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Groq response structure: {data}") from e


# ── Shared retry logic ─────────────────────────────────────────────────────────

def _post_with_retry(url: str, headers: dict, json: dict, extractor, retries: int = 5) -> str:
    last_error = None
    attempt = 0

    while True:
        try:
            response = requests.post(url, headers=headers, json=json, timeout=180)

            if response.status_code == 200:
                raw = extractor(response.json())
                return _strip_markdown_fences(raw.strip())

            elif response.status_code == 429:
                # Rate limited — wait exactly as long as the API tells us, then retry forever
                wait = 60  # safe default
                try:
                    msg = response.json().get("error", {}).get("message", "")
                    match = re.search(r"try again in (\d+(?:\.\d+)?)s", msg)
                    if match:
                        wait = int(float(match.group(1))) + 10  # add 10s buffer
                except Exception:
                    pass
                print(f"    [RATE LIMIT] Waiting {wait}s before retry (will keep trying)...")
                time.sleep(wait)
                continue  # retry immediately after wait — no attempt limit

            else:
                # Real API error (400, 401, 404 etc) — don't retry
                raise RuntimeError(
                    f"API error {response.status_code}: {response.text[:500]}"
                )

        except RuntimeError:
            raise  # bubble up real errors immediately

        except Exception as e:
            # Network error — retry up to `retries` times
            last_error = e
            attempt += 1
            if attempt < retries:
                print(f"    [RETRY {attempt}/{retries}] Network error: {e}")
                time.sleep(5)
            else:
                raise RuntimeError(f"Failed after {retries} network retries. Last error: {last_error}")


def _strip_markdown_fences(text: str) -> str:
    """Remove ```python ... ``` or ``` ... ``` wrappers if present."""
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
