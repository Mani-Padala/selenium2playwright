# java2playwright — AI-Powered Test Automation Migration Agent

> Converts Java Selenium + Cucumber projects into Python Playwright + pytest-bdd automatically using LLM-powered code conversion.

---

## The Problem This Solves

Enterprise QA teams spend weeks or months manually migrating legacy Java Selenium test suites to modern Python Playwright frameworks. This is:

- **Repetitive** — the same conversion patterns repeat across hundreds of files
- **Error-prone** — manual conversion misses edge cases
- **Expensive** — senior engineers doing mechanical work

This agent automates the entire migration pipeline end-to-end.

---

## How It Works

```
Java Selenium Project (input)
        ↓
  [1] File Scanner       — walks project, strips noise to reduce tokens
        ↓
  [2] Pattern Learner    — sends reference Python project to LLM, extracts idioms
        ↓
  [3] LLM Converter      — converts each Java file to Python using extracted patterns
        ↓
  [4] File Writer        — mirrors folder structure, generates scaffold files
        ↓
Python Playwright Project (output) — ready to run
```

### What gets converted

| Java                                | Python                           |
| ----------------------------------- | -------------------------------- |
| Selenium `WebDriver`                | Playwright `Page`                |
| Cucumber `@Given/@When/@Then`       | pytest-bdd `@given/@when/@then`  |
| `@BeforeAll / @AfterAll`            | Session-scoped pytest fixtures   |
| `@Before / @After`                  | Function-scoped pytest fixtures  |
| `driver.findElement(By.id("x"))`    | `page.locator("#x")`             |
| `driver.findElement(By.xpath("x"))` | `page.locator("xpath=x")`        |
| Applitools Eyes (Selenium SDK)      | Applitools Eyes (Playwright SDK) |
| JUnit / TestNG runner               | `pytest.ini` + pytest-bdd        |
| Maven `pom.xml`                     | `requirements.txt`               |

---

## Key Engineering Decisions

### 1. LLM-powered conversion over rule-based

Rule-based regex converters break on edge cases. An LLM understands context — it handles complex method chains, custom utilities, and framework-specific patterns that no regex can capture.

### 2. Pattern learning from reference project

The agent reads a reference Python project first and extracts idioms before converting. This means output code matches the team's existing style — not just generic Playwright code.

### 3. Checkpoint / resume for large projects

Enterprise projects have 100s of files. If a run is interrupted (rate limit, network, etc), the agent saves progress after every file and resumes from exactly where it left off — no re-work.

### 4. Multi-provider LLM support

The agent works with Claude, Gemini, and Groq. If one provider hits rate limits or costs are a concern, switching providers is one flag change: `--provider groq`.

### 5. API key rotation

When one API key exhausts its quota mid-run, the agent automatically rotates to the next key in the pool and continues without stopping. No manual intervention needed.

### 6. Token optimization

Java source files are preprocessed before sending to the LLM — comments, blank lines, package declarations, and `@Override` annotations are stripped. This reduces token usage by ~40%, cutting costs and staying within rate limits.

---

## Project Structure

```
java2playwright/
├── agent.py          # CLI entrypoint — orchestrates the pipeline
├── scanner.py        # Walks Java project, maps Java packages to Python folders
├── learner.py        # Extracts patterns from Python reference project via LLM
├── converter.py      # Converts each Java file to Python via LLM
├── writer.py         # Writes output files and generates scaffold
├── llm_client.py     # Unified LLM client (Claude / Gemini / Groq)
├── prompts.py        # All LLM prompt templates
└── java2python/      # Output folder — one subfolder per converted project
    └── <project_name>/
        ├── conftest.py
        ├── features/
        ├── tests/
        ├── pages/
        ├── utils/
        ├── domain/
        └── requirements.txt
```

---

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-username/java2playwright
cd java2playwright

# 2. Create virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

# 3. Install dependencies
pip install requests

# 4. Set your API key (Groq is free)
# Get a free key at console.groq.com
# Via environment variables: supports up to 9 keys (GROQ_API_KEY through GROQ_API_KEY_9)
set GROQ_API_KEY=your_key_1        # Windows
set GROQ_API_KEY_2=your_key_2
set GROQ_API_KEY_3=your_key_3
# ... up to GROQ_API_KEY_9
export GROQ_API_KEY=your_key_1     # Mac/Linux

# Via --key flag: unlimited keys (pass as many as you have)
# python agent.py --java "path" --key key1 key2 key3 key4 key5 ...
```

---

## Usage

```bash
# Basic — converts Java project using Groq (free)
python agent.py --java "path/to/java/project"

# With multiple API keys — no limit on number of keys
# Agent auto-rotates to the next key when current one hits rate limit or quota
python agent.py --java "path/to/java/project" --key key1 key2
python agent.py --java "path/to/java/project" --key key1 key2 key3
python agent.py --java "path/to/java/project" --key key1 key2 key3 key4 key5

# Resume after interruption — same command, picks up where it left off
python agent.py --java "path/to/java/project" --key key1 key2

# Use Claude (better quality, paid)
python agent.py --java "path/to/java/project" --provider claude --key sk-ant-...

# Dry run — scan and extract patterns only, no conversion
python agent.py --java "path/to/java/project" --dry

# Reset — clear checkpoint and re-convert everything
python agent.py --java "path/to/java/project" --reset
```

---

## Supported LLM Providers

| Provider         | Free Tier         | Quality | Speed     |
| ---------------- | ----------------- | ------- | --------- |
| Groq (default)   | Yes — 500 req/day | Good    | Very fast |
| Google Gemini    | Yes — limited     | Good    | Fast      |
| Anthropic Claude | No — paid         | Best    | Fast      |

Switch provider with `--provider claude/gemini/groq`

---

## Rate Limit Handling

The agent handles rate limits gracefully at three levels:

1. **Between-file delay** — configurable pause between API calls (20s for Groq)
2. **Auto-retry** — waits the exact time the API tells us, then retries indefinitely
3. **Key rotation** — when one key exhausts its quota, switches to the next key automatically
4. **Checkpoint/resume** — if all keys are exhausted, progress is saved and the next run resumes from the last completed file

---

## Validated On

- [x] `example-selenium-java-cucumber` — Applitools demo project (2 files, full end-to-end pass)
- [x] `MasterSeleniumFramework_BDD` — Enterprise-style BDD framework (38 files, Page Object Model, RestAssured API calls, custom types, email utilities)

---

## Limitations & Known Gaps

- **No JUnit 5 @ParameterizedTest support** — parametrized tests need manual review
- **RestAssured → requests** — API test conversion works but may need endpoint adjustments
- **PicoContainer DI** — replaced with pytest fixtures, wiring may need review
- **Email utilities** — Java Mail API has no direct Python equivalent, stubs are generated

---

## Future Improvements

- [ ] Support for TestNG `@DataProvider` → pytest parametrize
- [ ] Parallel execution config generation (`pytest-xdist`)
- [ ] HTML conversion report showing before/after for each file
- [ ] Web UI for non-technical stakeholders to trigger conversions
- [ ] Support for Spring-based test frameworks

---

## Tech Stack

| Layer              | Technology                                    |
| ------------------ | --------------------------------------------- |
| Language           | Python 3.10+                                  |
| LLM providers      | Anthropic Claude, Google Gemini, Groq (Llama) |
| Output framework   | Playwright + pytest-bdd                       |
| Visual testing     | Applitools Eyes                               |
| Checkpoint storage | JSON                                          |

---

## Author

Built as a portfolio project to demonstrate AI-powered automation engineering.
Inspired by real enterprise Java-to-Python migration initiatives.
