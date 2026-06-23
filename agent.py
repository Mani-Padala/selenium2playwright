import argparse
import json
import os
import sys
import time
from pathlib import Path

from scanner import (
    scan_java_project,
    scan_python_ref_project,
    java_to_python_path,
    build_import_map,
)
from learner import extract_patterns
from converter import convert_java_file, generate_conftest
from writer import write_output, print_summary

DEFAULT_REF = r"C:\Users\padal\modern-playwright-python"
OUTPUT_BASE = Path(__file__).parent / "java2python"

PROVIDER_ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq":   "GROQ_API_KEY",
}

RATE_LIMIT_DELAY = {"claude": 0, "gemini": 2, "groq": 20}


class KeyRotator:
    """
    Manages a pool of API keys.
    Rotates to the next key when current one hits rate limit or quota.
    Supports passing multiple keys via --key key1 key2
    or environment variables GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3 etc.
    """
    def __init__(self, keys: list, provider: str):
        self.keys = [k for k in keys if k]
        self.provider = provider
        self.index = 0
        if not self.keys:
            print(f"\n[ERROR] No API keys provided for provider '{provider}'.")
            sys.exit(1)
        print(f"  Key pool: {len(self.keys)} key(s) loaded for {provider}")

    def current(self) -> str:
        return self.keys[self.index]

    def rotate(self, reason: str = "") -> bool:
        if len(self.keys) == 1:
            return False
        next_index = self.index + 1
        if next_index >= len(self.keys):
            print(f"\n  [KEY POOL EXHAUSTED] All {len(self.keys)} keys have hit their limits.")
            print("  Progress saved - re-run tomorrow to resume.")
            return False
        self.index = next_index
        print(f"\n  [KEY ROTATION] Switched to key {self.index + 1}/{len(self.keys)}"
              + (f" - {reason}" if reason else ""))
        return True


def checkpoint_path(out_path: Path) -> Path:
    return out_path / ".conversion_checkpoint.json"


def load_checkpoint(out_path: Path) -> dict:
    cp = checkpoint_path(out_path)
    if cp.exists():
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            data["completed"] = set(data.get("completed", []))
            print(f"  [RESUME] Checkpoint found - {len(data['completed'])} file(s) already converted.")
            return data
        except Exception:
            pass
    return {"completed": set(), "patterns": None}


def save_checkpoint(out_path: Path, completed: set, patterns: str) -> None:
    cp = checkpoint_path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)
    data = {"completed": list(completed), "patterns": patterns}
    cp.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_checkpoint(out_path: Path) -> None:
    cp = checkpoint_path(out_path)
    if cp.exists():
        cp.unlink()
        print("  [RESET] Checkpoint cleared - will re-convert all files.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Java Selenium+Cucumber project to Python Playwright+pytest-bdd.\n"
                    "Supports checkpoint/resume and multi-key rotation.\n\n"
                    "Examples:\n"
                    "  Single key:   python agent.py --java C:/project\n"
                    "  Two keys:     python agent.py --java C:/project --key key1 key2\n"
                    "  Resume:       python agent.py --java C:/project --key key1 key2\n"
                    "  Fresh start:  python agent.py --java C:/project --reset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--java", required=True,
                        help="Path to the root of the Java Selenium project")
    parser.add_argument("--ref", default=DEFAULT_REF,
                        help="Path to the Python Playwright reference project")
    parser.add_argument("--provider", default="groq",
                        choices=["claude", "gemini", "groq"],
                        help="LLM provider (default: groq)")
    parser.add_argument("--key", nargs="+", default=None,
                        help="One or more API keys. Auto-rotates on rate limit.")
    parser.add_argument("--dry", action="store_true",
                        help="Dry run: scan and learn patterns only")
    parser.add_argument("--reset", action="store_true",
                        help="Clear checkpoint and re-convert all files from scratch")
    return parser.parse_args()


def resolve_keys(cli_keys, provider: str) -> list:
    if cli_keys:
        return cli_keys
    env_var = PROVIDER_ENV_KEYS.get(provider, "API_KEY")
    keys = []
    if os.environ.get(env_var):
        keys.append(os.environ[env_var])
    for i in range(2, 10):
        val = os.environ.get(f"{env_var}_{i}")
        if val:
            keys.append(val)
    if not keys:
        print(
            f"\n[ERROR] No API key found for provider '{provider}'.\n"
            f"  Set via --key or environment variable {env_var}\n"
            f"  For multiple keys: {env_var}, {env_var}_2, {env_var}_3\n"
        )
        sys.exit(1)
    return keys


def main() -> None:
    args = parse_args()
    keys = resolve_keys(args.key, args.provider)
    rotator = KeyRotator(keys, args.provider)
    out_path = OUTPUT_BASE / Path(args.java).resolve().name

    print("\n" + "=" * 55)
    print("  java2playwright - Java to Python Playwright Agent")
    print("=" * 55)
    print(f"  Java project : {args.java}")
    print(f"  LLM provider : {args.provider}")
    print(f"  API keys     : {len(keys)} key(s) in pool")
    print(f"  Output       : {out_path}")
    print(f"  Dry run      : {args.dry}")
    print(f"  Reset        : {args.reset}")
    print("=" * 55 + "\n")

    if args.reset:
        clear_checkpoint(out_path)

    # STEP 1: Scan Java project
    print("[1/5] Scanning Java project...")
    try:
        all_java_files = scan_java_project(args.java)
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    java_files = [(p, c) for p, c in all_java_files if Path(p).suffix.lower() == ".java"]
    feature_files = [(p, c) for p, c in all_java_files if Path(p).suffix.lower() == ".feature"]

    print(f"  Found {len(java_files)} Java file(s) and {len(feature_files)} feature file(s)")

    if not java_files:
        print("\n[WARN] No .java files found. Nothing to convert.")
        sys.exit(0)

    import_map = build_import_map(java_files)
    feature_file_list = "\n".join(
        Path(java_to_python_path(p)).name for p, _ in feature_files
    )

    # STEP 2: Load checkpoint
    checkpoint = load_checkpoint(out_path)
    completed = checkpoint["completed"]
    remaining = [(p, c) for p, c in java_files if p not in completed]
    skipped = len(java_files) - len(remaining)

    if skipped:
        print(f"\n  [RESUME] Skipping {skipped} already-converted file(s).")
        print(f"  [RESUME] {len(remaining)} file(s) left to convert.")

    # STEP 3: Scan reference project
    print("\n[2/5] Scanning Python reference project...")
    try:
        ref_files = scan_python_ref_project(args.ref)
        print(f"  Found {len(ref_files)} Python reference file(s)")
    except FileNotFoundError as e:
        print(f"\n[WARN] {e}")
        ref_files = []

    # STEP 4: Extract patterns (use cached if resuming)
    print("\n[3/5] Extracting patterns via LLM...")
    if checkpoint.get("patterns") and skipped:
        patterns = checkpoint["patterns"]
        print("  [RESUME] Using cached patterns from previous run.")
    else:
        patterns = extract_patterns(ref_files, rotator.current(), provider=args.provider)
        save_checkpoint(out_path, completed, patterns)

    if args.dry:
        print("\n[DRY RUN] Patterns extracted. Skipping conversion.")
        print(patterns)
        return

    # STEP 5: Convert remaining files
    total = len(java_files)
    print(f"\n[4/5] Converting {len(remaining)} remaining file(s) (of {total} total)...")

    delay = RATE_LIMIT_DELAY.get(args.provider, 5)
    if delay and remaining:
        print(f"  (Pausing {delay}s between files for {args.provider} rate limits)")

    converted_files = []
    all_keys_exhausted = False

    for i, (java_rel_path, java_content) in enumerate(remaining, 1):
        filename = Path(java_rel_path).name
        done = len(completed)
        print(f"  [{done + i}/{total}] Converting {filename} "
              f"[key {rotator.index + 1}/{len(rotator.keys)}]...")

        if delay and i > 1:
            time.sleep(delay)

        success = False
        for attempt in range(len(rotator.keys) + 1):
            try:
                python_content = convert_java_file(
                    java_rel_path=java_rel_path,
                    java_content=java_content,
                    patterns=patterns,
                    import_map=import_map,
                    feature_files=feature_file_list,
                    api_key=rotator.current(),
                    provider=args.provider,
                )
                python_rel_path = java_to_python_path(java_rel_path)
                converted_files.append((python_rel_path, python_content))
                print(f"         -> {python_rel_path}")
                completed.add(java_rel_path)
                save_checkpoint(out_path, completed, patterns)
                success = True
                break

            except RuntimeError as e:
                err_str = str(e)
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    switched = rotator.rotate(reason="rate limit / quota exhausted")
                    if switched:
                        print(f"  [RETRY] Retrying {filename} with key {rotator.index + 1}...")
                        continue
                    else:
                        all_keys_exhausted = True
                        break
                else:
                    print(f"  [ERROR] Failed to convert {filename}: {e}")
                    break

        if all_keys_exhausted:
            print("  [STOP] All keys exhausted. Progress saved.")
            break

        if not success:
            stub = f"# CONVERSION FAILED for {filename}\n# Re-run to retry.\n"
            python_rel_path = java_to_python_path(java_rel_path)
            converted_files.append((python_rel_path, stub))

    # Generate conftest.py
    print("  Generating conftest.py...")
    try:
        conftest_content = generate_conftest(patterns, rotator.current(), provider=args.provider)
    except Exception as e:
        print(f"  [ERROR] Failed to generate conftest.py: {e}")
        conftest_content = f"# GENERATION FAILED\n# Error: {e}\n"

    # STEP 6: Write output
    print(f"\n[5/5] Writing output to: {out_path}")
    write_output(
        output_root=str(out_path),
        converted_files=converted_files,
        conftest_content=conftest_content,
        feature_files=feature_files,
    )

    all_done = len(completed) == len(java_files)
    if all_done:
        clear_checkpoint(out_path)
        print("\n  All files converted - checkpoint cleared.")
    else:
        remaining_count = len(java_files) - len(completed)
        print(f"\n  {remaining_count} file(s) still pending.")
        if all_keys_exhausted:
            print("  All API keys exhausted for today.")
        print("  Re-run the same command tomorrow to resume.")

    print_summary(str(out_path))


if __name__ == "__main__":
    main()