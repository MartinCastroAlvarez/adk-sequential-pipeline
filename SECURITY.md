# Security

adk-sequential-pipeline runs six LLM agents over a folder of local documents and a topic
typed by a user. The model's output is untrusted, the documents may be untrusted, and the
topic certainly is. Design goals: agents can only read the source pack, only call the
tools they need, never see PII from the topic, can't end the review loop by lying, can't
spend without bound, and nothing leaves the machine unless you opt in.

## Reporting a vulnerability

Open a private security advisory at
<https://github.com/MartinCastroAlvarez/adk-sequential-pipeline/security/advisories/new>.
Do **not** open a public issue for a suspected vulnerability. We acknowledge within 5
business days and aim to ship a fix within 30 days. You are credited in the advisory
unless you ask otherwise. A tool call that escapes the allowlist or reads outside the
source pack is in scope and very welcome.

Supported versions: the latest minor release.

## 1. Threat model

**Assets.** The files on the machine, the source pack, the session state (topic, notes,
drafts, reviews), environment variables (an optional `GOOGLE_API_KEY`), and the model
endpoint and its compute budget.

| Actor | Controls | Must not be able to |
| --- | --- | --- |
| The user | the topic (one message) | inject instructions that agents follow, plant PII in prompts or state, change the pipeline |
| A source author | the text of a `*.md` note in the pack | escape its data block, inject template placeholders, read other files |
| The model (any agent) | text, tool calls and their arguments, structured outputs | call another agent's tools, read files by path, end the critic loop with a failing score, spend past the budget, write PII into state |
| Whoever controls `OLLAMA_HOST` | where prompts are sent | receive prompts without your explicit opt-in |

| Threat | Control |
| --- | --- |
| Reading arbitrary files | Tools take a `source_id` matching `[a-z0-9][a-z0-9-]{0,63}`, looked up in an in-memory index built once from `*.md` files in one folder; there is no path parameter anywhere (tested: `../`, absolute paths, `.md` suffixes, spaces). Symlinks and oddly named files are skipped; files over 64 KB or packs over 200 files are refused. |
| Tool misuse | `before_tool_callback` enforces `TOOL_ALLOWLIST` per agent: a call outside it returns `{"error": ...}` and the tool never runs (tested with a planted `delete_everything` tool and with a narrowed allowlist). Each agent's `tools` list is already minimal; the allowlist is the second line. |
| Ending the loop early | The critic's `after_model_callback` removes an `exit_loop` call unless the same response carries a verdict with `score >= threshold` and `approved: true` (tested: failing score, lying `approved`, no verdict). `max_iterations` bounds the loop either way. |
| Prompt injection via the topic | The topic is capped at 200 characters, PII-redacted, and `& < > { }` are neutralized before it enters state; every instruction puts inputs in `<tag>` blocks declared to be data. |
| Prompt injection via sources | Source text is neutralized (`& < > { }`) at load time, so a note can't close a block (`</research_notes>`) or add a placeholder. Neutralizing reduces injection; it can't remove it: a note can still say false things persuasively. Only use sources you trust as much as you trust their content. |
| Prompt injection via model output | Model text that flows to the next agent (`research_notes`, `draft`) is templated inside `<tag>` blocks. ADK fills placeholders in one pass, so a `{key}` in model output is not expanded again. Structured outputs are validated with pydantic `extra="forbid"` schemas; a malformed answer fails the run instead of passing on garbage. |
| PII in prompts or state | `before_model_callback` redacts emails, API-key shapes (`sk-...`, `AIza...`), card-, SSN- and phone-like numbers and IPv4 addresses in the system instruction and every content part; `after_model_callback` redacts the model's text before ADK writes it to state (tested end to end). It is a regex heuristic, not a DLP system. |
| Runaway cost | `before_model_callback` refuses a request over `DESK_MAX_REQUEST_TOKENS` and a run over `DESK_MAX_RUN_TOKENS` (approximate, 4 chars per token) by raising `BudgetExceededError` before the model is called (tested). Tool inputs and outputs are capped (query 300, claim 600, read 4,000 characters). |
| Data leaving the machine | The default model is ollama on loopback; `OLLAMA_HOST` must be loopback unless `DESK_ALLOW_REMOTE_OLLAMA=1`. Gemini is used only with `DESK_PROVIDER=gemini` and your own key. Tests and CI use stub models. |
| Secrets in prompts or logs | This package reads no secret. `GOOGLE_API_KEY` is read by ADK only when you choose Gemini, and never enters a prompt or state. `.env` is git-ignored. |
| Code execution | No `eval`/`exec`/`compile`, no `pickle`/`yaml`, no `subprocess`/`shell=`; an AST test enforces it and allows no `# noqa`, `# nosec` or `# type: ignore` in the package. |

## 2. Operator notes

- **`adk web` is a development server.** Bind it to `127.0.0.1` (its default), never to a
  public interface: it has no authentication and runs the agent for anyone who reaches it.
- **Fact-checking is lexical.** `check_claim` proves a claim's words appear together in one
  source sentence. It catches invented claims, not every misreading. Review posts before
  publishing them.
- **Session state holds the drafts.** `InMemorySessionService` keeps them in memory only; if
  you switch to a persistent session service, the topic, notes and drafts are stored.

## 3. Dependencies

CI runs `bandit` on the package and `pip-audit` on the locked environment. Dependabot
alerts, security updates and secret scanning are enabled on the repository.

Known and accepted: **CVE-2026-114603** in `opentelemetry-api` 1.44 (quadratic parsing of
an oversized W3C `tracestate` header, fixed in 1.45.1). `google-adk` 2.13 pins
`opentelemetry-api<=1.44`, so the fix can't be installed until ADK relaxes the pin. It is
reachable only through a server that extracts trace context from untrusted requests; the
CLI, tests and `adk run` serve nothing, and `adk web` should stay on loopback. CI ignores
exactly this ID; remove the ignore when ADK allows 1.45.1.
