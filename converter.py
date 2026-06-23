"""
converter.py — Converts individual Java source files to Python using an LLM.
Supports Claude, Gemini, and Groq via llm_client.py.
"""

from pathlib import Path
from llm_client import call_llm
from prompts import (
    CONVERTER_SYSTEM,
    CONVERTER_USER,
    CONFTEST_SYSTEM,
    CONFTEST_USER,
)


def convert_java_file(
    java_rel_path: str,
    java_content: str,
    patterns: str,
    api_key: str,
    provider: str = "claude",
    import_map: str = "",
    feature_files: str = "",
) -> str:
    filename = Path(java_rel_path).name
    user_prompt = CONVERTER_USER.format(
        patterns=patterns,
        filename=filename,
        java_code=java_content,
        import_map=import_map or "(No import map provided)",
        feature_files=feature_files or "(No feature files found)",
    )
    # Groq free tier: use lower max_tokens to stay within TPM limits
    max_tokens = 2000 if provider == "groq" else 4000
    return call_llm(
        system=CONVERTER_SYSTEM,
        user=user_prompt,
        api_key=api_key,
        provider=provider,
        max_tokens=max_tokens,
    )


def generate_conftest(
    patterns: str,
    api_key: str,
    provider: str = "claude",
) -> str:
    user_prompt = CONFTEST_USER.format(patterns=patterns)
    max_tokens = 2000 if provider == "groq" else 4000
    return call_llm(
        system=CONFTEST_SYSTEM,
        user=user_prompt,
        api_key=api_key,
        provider=provider,
        max_tokens=max_tokens,
    )
