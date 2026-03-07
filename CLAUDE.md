# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup:**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY
```

**Run the agent (demo query):**
```bash
python -m agent.agent
python -m agent.agent -o output.txt  # write to specific file
```

**Run evals:**
```bash
python -m evals.run_evals                          # full suite, active prompt
python -m evals.run_evals --prompt-version v3      # specific version
python -m evals.run_evals --eval-id eval-001       # single case
python -m evals.run_evals --compare v3 v4          # head-to-head comparison
```

**Start the API:**
```bash
uvicorn api.main:app --reload
# POST /query with {"control_query": "CC6.1", "question": "..."}
# GET  /controls  to list available controls
```

## Architecture

### Data flow

1. User provides a `control_query` (e.g., "CC6.1") and a free-form question
2. `agent/agent.py` looks up the control in `data/controls.json` via keyword/ID matching
3. The control context is injected into a structured prompt (`agent/prompts.py`)
4. The Claude API returns a JSON response validated by Pydantic schemas (`agent/schemas.py`)
5. On parse failure, the agent retries up to `max_retries` times (default: 2)

### Key modules

- **`agent/prompts.py`** — All prompt templates, versioned v1–v4. `ACTIVE_SYSTEM_PROMPT` and `ACTIVE_SYSTEM_PROMPT_VERSION` point to the current production prompt. `PROMPT_VERSIONS` dict enables the eval harness to test any version. When iterating on prompts, add a new version constant and update `ACTIVE_*`.

- **`agent/schemas.py`** — Pydantic v2 models for both agent output (`ControlGuidanceResponse`, `EvidenceItem`) and eval scoring (`EvalResult`, `EvalScores`). Validators actively reject vague language (e.g., "best practices", "as appropriate") in evidence descriptions and enforce minimum step length.

- **`agent/agent.py`** — `ComplianceCopilot` class wraps API calls. `find_control()` does ID-exact → control_id → title substring matching (noted as a vector search candidate). The agent defaults to `claude-sonnet-4-6`; the LLM judge in evals uses `claude-opus-4-6`.

- **`evals/run_evals.py`** — Three-layer eval pipeline: Pydantic schema validation → ground truth keyword checks (`must_include`/`must_not_include`) → LLM-as-judge scoring. Results are saved to `evals/results/` as JSON, tracked in git.

- **`evals/eval_set.json`** — Ground truth dataset. Each case has `difficulty` (`standard`|`nuanced`|`clear-cut`|`edge-case`), `must_include`, `must_not_include`, `required_evidence_artifacts`, and `auditor_concerns`.

- **`data/controls.json`** — Control library for SOC 2, ISO 27001, NIST CSF. Each control entry has `key_requirements`, `common_evidence`, `aws_implementation`, `common_failures`, and `auditor_red_flags` — this is the grounding context injected into every prompt.

### Prompt versioning discipline

No prompt version ships without running the full eval suite and meeting all launch criteria (defined in `evals/rubric.md` and enforced by `EvalResult.passed`):
- Avg overall score >= 3.5
- Avg hallucination risk >= 4.0
- Avg factual accuracy >= 4.0
- Zero critical errors
- 100% pass rate on "clear-cut" cases

When adding a new prompt version: add a constant in `agent/prompts.py`, register it in `PROMPT_VERSIONS`, run `--compare` against the previous version, then update `ACTIVE_SYSTEM_PROMPT` only if it meets launch criteria.

### Agent output constraints (enforced by schema validators)

- `EvidenceItem.description` rejects vague phrases: "best practices", "as appropriate", "if applicable", "various methods"
- `implementation_steps` entries must be >= 15 characters
- `confidence` is an enum: `high | medium | low`
- `collection_method` is an enum: `manual | automated | tool-assisted`
- `max_tokens` is set to 8192 to prevent JSON truncation mid-response
