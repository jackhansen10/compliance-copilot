# compliance-copilot

An AI-powered compliance guidance agent for GRC and security teams. Ask questions about security controls — CC6.1, ISO 27001 A.8.2, NIST PR.AC-1, and more — and get concrete, auditor-aware implementation guidance, evidence checklists, and failure pattern analysis.

**This project is also a demonstration of AI product development practices** applied to a GRC domain: prompt engineering with explicit versioning, structured evaluation datasets, LLM-as-judge scoring, and launch readiness criteria. The goal is to show how a GRC SME can own the "truth layer" of an AI feature — not just describe compliance concepts, but build the scaffolding that makes AI outputs trustworthy and measurable.

---

## What It Does

Given a control ID and a question, the agent returns structured guidance including:

- Plain-language explanation of what the control actually requires
- Concrete implementation steps for AWS (GCP/Azure in roadmap)
- Evidence artifacts an auditor would expect, with collection methods
- Common implementation failures specific to this control
- Auditor perspective: what would get flagged and why
- Confidence level + explicit gaps when context is insufficient

**Example query:**
```
Control: SOC 2 CC6.1
Question: We're a 50-person SaaS company on AWS preparing for our first SOC 2 Type II.
         What do we need for this control and what evidence should we start collecting now?
```

---

## Project Structure

```
compliance-copilot/
├── agent/
│   ├── prompts.py       # Prompt templates, versioned v1–v4, with rationale
│   ├── agent.py         # Core agent: control retrieval, API calls, parsing + retry
│   └── schemas.py       # Pydantic output schemas with validation logic
├── evals/
│   ├── eval_set.json    # Ground-truth evaluation dataset (7 cases, expanding)
│   ├── run_evals.py     # Eval harness: rule checks + LLM-as-judge + comparison
│   ├── rubric.md        # Human review rubric with scoring criteria + launch gates
│   └── results/         # Eval run outputs, tracked in git for regression visibility
├── data/
│   └── controls.json    # Control library: SOC 2, ISO 27001, NIST CSF
├── api/
│   └── main.py          # FastAPI wrapper
└── notebooks/
    └── prompt_iteration.ipynb  # Prompt development log (coming soon)
```

---

## The AI Product Layer

The interesting part of this project isn't the agent itself — it's the infrastructure around it that makes the agent trustworthy.

### Prompt Versioning (`agent/prompts.py`)
Four prompt versions are tracked with explicit rationale for each change:
- **v1**: Baseline, no structure enforcement
- **v2**: Added output schema + "only use provided context" constraint
- **v3**: Added chain-of-thought reasoning steps
- **v4 (current)**: Added auditor persona + red flag emphasis, based on eval results showing v3 was too generic on audit risk

The eval harness can run any version and compare them head-to-head:
```bash
python -m evals.run_evals --compare v3 v4
```

### Ground Truth Dataset (`evals/eval_set.json`)
Each eval case includes:
- `must_include`: Claims that must be present in a correct response
- `must_not_include`: Dangerous or incorrect statements (e.g., "shared accounts are fine for small teams")
- `required_evidence_artifacts`: Specific artifacts auditors expect
- `auditor_concerns`: What would flag as a finding
- `difficulty`: `standard` | `nuanced` | `clear-cut` | `edge-case`

The "clear-cut" and "edge-case" categories are particularly important: the agent must get simple questions unambiguously right, and must handle off-topic or adversarial inputs gracefully.

### Evaluation Harness (`evals/run_evals.py`)
Three layers of evaluation:
1. **Schema validation** (Pydantic) — did the response parse at all?
2. **Ground truth rule checks** — keyword matching against `must_include` / `must_not_include`
3. **LLM-as-judge** — scores 5 dimensions: factual accuracy, completeness, specificity, hallucination risk, audit readiness

### Human Review Rubric (`evals/rubric.md`)
Structured rubric for human review with:
- 5 scoring dimensions with defined criteria at each score level
- "Red flag phrases" that auto-cap a score (e.g., "implement best practices")
- Critical error taxonomy (automatic failures)
- **Launch readiness criteria**: minimum bar before shipping a prompt version

### Launch Readiness Gate
A prompt version ships when:
- Avg overall score ≥ 3.5
- Avg hallucination risk ≥ 4.0
- Avg factual accuracy ≥ 4.0
- Zero critical errors
- 100% pass rate on "clear-cut" cases

---

## Quick Start

```bash
git clone https://github.com/yourusername/compliance-copilot
cd compliance-copilot
pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY
```

**Run the agent directly:**
```bash
python -m agent.agent
```

**Run the eval suite:**
```bash
python -m evals.run_evals
```

**Compare prompt versions:**
```bash
python -m evals.run_evals --compare v3 v4
```

**Start the API:**
```bash
uvicorn api.main:app --reload
# Then: POST /query with {"control_query": "CC6.1", "question": "..."}
```

---

## Controls Covered

| Framework | Control ID | Title |
|-----------|-----------|-------|
| SOC 2 | CC6.1 | Logical Access Security Measures |
| SOC 2 | CC7.2 | Monitoring of Security Events |
| SOC 2 | CC9.2 | Vendor and Business Partner Risk |
| ISO 27001 | A.8.2 | Information Classification |
| NIST CSF | PR.AC-1 | Identities and Credentials |

*Expanding to HIPAA, PCI DSS, and additional SOC 2 criteria — contributions welcome.*

---

## Roadmap

- [ ] Vector search over control library (semantic control lookup)
- [ ] Multi-framework cross-mapping (e.g., "what ISO 27001 controls map to this SOC 2 criteria?")
- [ ] HIPAA and PCI DSS control library
- [ ] GCP and Azure implementation guidance
- [ ] Streamlit demo UI
- [ ] Prompt iteration notebook with before/after examples
- [ ] Automated regression testing on eval results in CI

---

## Design Principles

**Ground responses in context, not memory.** The agent is explicitly constrained to use provided control context. When context is insufficient, it says so — and explains what's missing. This reduces hallucination risk on a domain where incorrect guidance has real consequences.

**Treat "I don't know" as a valid, important output.** The `confidence` field and `context_gaps` field exist for a reason. A compliance agent that confidently answers everything is more dangerous than one that flags uncertainty.

**Evals are first-class artifacts.** The eval dataset isn't a test suite — it's the "truth layer" of the product. It gets updated when new failure patterns emerge, when the framework evolves, or when user questions reveal gaps in coverage.

**Prompt changes require eval evidence.** No prompt version ships without running the full eval suite and meeting launch criteria. The comparison capability in `run_evals.py` exists to make this frictionless.

---

## Background

Built by Jack Hansen — GRC Automation Engineer at Salesforce with 6+ years in cloud security and compliance automation. This project explores the intersection of GRC domain expertise and AI product development: specifically, how to build the evaluation infrastructure that makes an AI feature trustworthy enough to rely on in a compliance context.