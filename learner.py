"""
learner.py — Reads the Python reference project and extracts reusable
Playwright + Applitools patterns via an LLM.
"""

from typing import List, Tuple
from llm_client import call_llm
from prompts import PATTERN_LEARNER_SYSTEM, PATTERN_LEARNER_USER
from scanner import format_files_for_prompt


def extract_patterns(
    ref_files: List[Tuple[str, str]],
    api_key: str,
    provider: str = "claude",
) -> str:
    if not ref_files:
        print("  [WARN] No Python reference files found. Using default patterns.")
        return "(No reference project found — using default Playwright + Applitools patterns.)"

    print(f"  Sending {len(ref_files)} reference file(s) to {provider} for pattern extraction...")

    reference_block = format_files_for_prompt(ref_files)
    user_prompt = PATTERN_LEARNER_USER.format(reference_files=reference_block)

    patterns = call_llm(
        system=PATTERN_LEARNER_SYSTEM,
        user=user_prompt,
        api_key=api_key,
        provider=provider,
        max_tokens=4000,
    )

    print(f"  Pattern extraction complete ({len(patterns)} chars).")
    return patterns
