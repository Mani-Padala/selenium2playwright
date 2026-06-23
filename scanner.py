"""
scanner.py — Walks a Java project directory and collects source files.
Skips build artifacts (target/, .git/, .github/) and binary files.
"""

import os
import re
from pathlib import Path
from typing import List, Tuple

# Directories to always skip
SKIP_DIRS = {".git", ".github", "target", "build", ".idea", ".mvn", "__pycache__"}

# File extensions to collect from the Java project
JAVA_EXTENSIONS = {".java", ".feature", ".xml", ".properties", ".yml", ".yaml"}

# File extensions to collect from the Python reference project
PYTHON_EXTENSIONS = {".py", ".feature", ".cfg", ".ini", ".toml", ".txt"}

# Files to skip by name (binaries, lock files, etc.)
SKIP_FILES = {"chromedriver.exe", "geckodriver.exe", "chromedriver", "geckodriver"}

# Java package folders that map to specific Python output folders
# Order matters — more specific matches first
JAVA_PACKAGE_TO_PYTHON_FOLDER = {
    "stepdefinitions": "tests",
    "steps":           "tests",
    "runners":         "tests",
    "hooks":           "tests",
    "pages":           "pages",
    "page":            "pages",
    "utils":           "utils",
    "util":            "utils",
    "helpers":         "utils",
    "factory":         "utils",
    "apis":            "api",
    "api":             "api",
    "domainobjects":   "domain",
    "domain":          "domain",
    "models":          "domain",
    "enums":           "enums",
    "constants":       "constants",
    "config":          "config",
    "context":         "context",
    "customtype":      "customtype",
    "java_mail_api":   "utils",
}

# Only step definition / hook / runner files get the test_ prefix
TEST_PREFIX_FOLDERS = {"stepdefinitions", "steps", "runners", "hooks"}


def _should_skip_dir(dir_name: str) -> bool:
    return dir_name in SKIP_DIRS or dir_name.startswith(".")


def scan_java_project(root: str) -> List[Tuple[str, str]]:
    """
    Walk a Java Maven project and return a list of (relative_path, file_content) tuples.
    Only collects .java and .feature files (the ones we need to convert).
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Java project not found: {root}")

    results = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        for filename in filenames:
            if filename in SKIP_FILES:
                continue

            ext = Path(filename).suffix.lower()
            if ext not in JAVA_EXTENSIONS:
                continue

            full_path = Path(dirpath) / filename
            rel_path = full_path.relative_to(root_path)

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                content = preprocess_java(content)  # strip noise to reduce tokens
                results.append((str(rel_path), content))
            except Exception as e:
                print(f"  [WARN] Could not read {full_path}: {e}")

    def sort_key(item):
        path, _ = item
        ext = Path(path).suffix.lower()
        if ext == ".java":
            return (0, path)
        elif ext == ".feature":
            return (1, path)
        else:
            return (2, path)

    results.sort(key=sort_key)
    return results


def scan_python_ref_project(root: str) -> List[Tuple[str, str]]:
    """
    Walk the Python reference project and return (relative_path, content) tuples.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(
            f"Python reference project not found: {root}\n"
            f"Please check the --ref path."
        )

    SKIP_REF_DIRS = SKIP_DIRS | {
        "venv", ".venv", "env", ".env", "node_modules",
        "__pycache__", ".pytest_cache", ".mypy_cache",
    }

    results = []
    MAX_FILE_BYTES = 20_000

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_REF_DIRS and not d.startswith(".")]

        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext not in PYTHON_EXTENSIONS:
                continue

            full_path = Path(dirpath) / filename
            rel_path = full_path.relative_to(root_path)

            try:
                raw = full_path.read_bytes()
                if len(raw) > MAX_FILE_BYTES:
                    content = raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
                    content += f"\n# ... [truncated at {MAX_FILE_BYTES} bytes]"
                else:
                    content = raw.decode("utf-8", errors="replace")
                results.append((str(rel_path), content))
            except Exception as e:
                print(f"  [WARN] Could not read {full_path}: {e}")

    results.sort(key=lambda x: x[0])
    return results


def format_files_for_prompt(files: List[Tuple[str, str]]) -> str:
    """Format (path, content) tuples into a string for LLM prompts."""
    parts = []
    for rel_path, content in files:
        parts.append(f"### FILE: {rel_path}\n```\n{content}\n```")
    return "\n\n".join(parts)


def java_to_python_path(java_rel_path: str) -> str:
    """
    Convert a Java relative path to the correct Python output path,
    preserving the logical folder structure of the project.

    Java package folder → Python folder mapping:
      stepdefinitions/ → tests/        (with test_ prefix)
      pages/           → pages/        (no test_ prefix)
      utils/           → utils/        (no test_ prefix)
      domainobjects/   → domain/       (no test_ prefix)
      enums/           → enums/        (no test_ prefix)
      constants/       → constants/    (no test_ prefix)
      hooks/           → tests/        (with test_ prefix)
      runners/         → tests/        (with test_ prefix)
      apis/            → api/          (no test_ prefix)
      factory/         → utils/        (no test_ prefix)

    Examples:
      src/test/java/awesomecucumber/stepdefinitions/CartStepDefinitions.java
        → tests/test_cart_step_definitions.py

      src/test/java/awesomecucumber/pages/BasePage.java
        → pages/base_page.py

      src/test/java/awesomecucumber/domainobjects/Product.java
        → domain/product.py

      src/test/resources/features/add_to_cart.feature
        → features/add_to_cart.feature
    """
    p = Path(java_rel_path)
    ext = p.suffix.lower()
    stem = p.stem
    snake = _camel_to_snake(stem)

    if ext == ".feature":
        return str(Path("features") / f"{_camel_to_snake(stem)}.feature")

    if ext != ".java":
        return str(Path("config") / p.name)

    # Find the Java package folder from the path parts
    parts_lower = [part.lower() for part in p.parts]

    python_folder = "tests"       # default fallback
    needs_test_prefix = True      # default: add test_ prefix

    for part_lower in parts_lower:
        if part_lower in JAVA_PACKAGE_TO_PYTHON_FOLDER:
            python_folder = JAVA_PACKAGE_TO_PYTHON_FOLDER[part_lower]
            needs_test_prefix = part_lower in TEST_PREFIX_FOLDERS
            break

    filename = f"test_{snake}.py" if needs_test_prefix else f"{snake}.py"
    return str(Path(python_folder) / filename)


def get_java_package_structure(files: List[Tuple[str, str]]) -> dict:
    """
    Analyse the Java project and return a mapping of
    java_rel_path → python_rel_path for all files.
    Useful for injecting into the LLM prompt so it knows correct import paths.
    """
    mapping = {}
    for java_path, _ in files:
        if Path(java_path).suffix.lower() == ".java":
            mapping[java_path] = java_to_python_path(java_path)
    return mapping


def build_import_map(files: List[Tuple[str, str]]) -> str:
    """
    Build a string showing Java class → Python module mapping.
    Injected into the converter prompt so the LLM uses correct imports.

    Example output:
      BasePage        → from pages.base_page import BasePage
      CartStepDefinitions → from tests.test_cart_step_definitions import ...
      Product         → from domain.product import Product
    """
    lines = []
    for java_path, _ in files:
        p = Path(java_path)
        if p.suffix.lower() != ".java":
            continue
        class_name = p.stem
        py_path = java_to_python_path(java_path)
        # Convert path to module: pages/base_page.py → pages.base_page
        module = py_path.replace("\\", "/").replace(".py", "").replace("/", ".")
        lines.append(f"  {class_name:40s} → from {module} import {class_name}")
    return "\n".join(lines)


def preprocess_java(content: str) -> str:
    """
    Strip noise from Java source to reduce token count before sending to LLM.
    Removes:
      - Block comments (/* ... */)
      - Javadoc comments (/** ... */)
      - Single line comments (//)
      - Blank lines
      - Common verbose Java boilerplate (package declaration, some annotations)
    Preserves all actual logic, class structure, method signatures, and annotations
    that affect behavior (@Given, @When, @Before etc).
    """
    import re

    # Remove block comments and javadoc (/* ... */ and /** ... */)
    content = re.sub(r'/\*[\s\S]*?\*/', '', content)

    # Remove single line comments (//) but keep the line
    content = re.sub(r'//[^\n]*', '', content)

    # Remove blank lines (lines with only whitespace)
    lines = content.splitlines()
    lines = [line for line in lines if line.strip()]

    # Remove package declaration (we don't need it — import map handles this)
    lines = [l for l in lines if not l.strip().startswith('package ')]

    # Remove @SuppressWarnings annotations
    lines = [l for l in lines if '@SuppressWarnings' not in l]

    # Remove @Override annotations
    lines = [l for l in lines if l.strip() != '@Override']

    return '\n'.join(lines)


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase or PascalCase to snake_case."""
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
    return s2.lower()