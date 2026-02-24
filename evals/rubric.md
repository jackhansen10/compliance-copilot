# Compliance Copilot — Output Evaluation Rubric

## Purpose

This rubric is used for human review of agent outputs during:
- **Pre-launch quality gates** (before shipping a new prompt version)
- **Regression testing** (after model or prompt changes)
- **Ongoing quality monitoring** (random sampling of production outputs)

Use this rubric alongside `run_evals.py` (automated LLM-as-judge). Human review is required for any response scoring below 3.5 overall, and for a 5% random sample of all production outputs.

---

## How to Use This Rubric

1. For each response, score each dimension independently (1–5)
2. Flag any **critical errors** — these are automatic failures regardless of other scores
3. Note specific quotes or examples from the response to support your scores
4. Record your review in the `results/` directory using the standard format

---

## Scoring Dimensions

### 1. Factual Accuracy (1–5)
*Does the response contain correct, verifiable information about the control?*

| Score | Criteria |
|-------|----------|
| 5 | All claims are correct. Control requirements, evidence types, and AWS services are accurately described. |
| 4 | Mostly correct with minor imprecision (e.g., slightly wrong service name, non-critical omission). |
| 3 | One substantive error that could mislead a compliance team, but nothing that would cause a direct audit failure. |
| 2 | Multiple errors, or one error that could directly cause an audit finding if followed. |
| 1 | Significantly incorrect. Following this guidance would likely result in audit findings. |

**Examples of factual errors to watch for:**
- Claiming a service doesn't exist or has wrong capabilities (e.g., "CloudTrail doesn't log S3 events")
- Misidentifying which SOC 2 criteria a control falls under
- Stating incorrect frequency requirements (e.g., "access reviews must be monthly" — there's no universal requirement)
- Confusing SOC 2 Type I vs. Type II requirements

---

### 2. Completeness (1–5)
*Does the response address all key aspects of the user's question?*

| Score | Criteria |
|-------|----------|
| 5 | Fully addresses the question. All required elements from ground truth are present. |
| 4 | Addresses the main question well. Minor gaps in coverage (e.g., missing one evidence artifact). |
| 3 | Addresses the primary question but misses a significant component (e.g., doesn't mention DPAs for vendor PII question). |
| 2 | Only partially answers the question. Key omissions that would leave a practitioner uncertain. |
| 1 | Superficial answer that doesn't meaningfully address the question. |

---

### 3. Specificity (1–5)
*Are recommendations concrete and actionable, or vague and generic?*

| Score | Criteria |
|-------|----------|
| 5 | Highly specific: names exact AWS services, Config rule names, IAM policy patterns, artifact names. |
| 4 | Mostly specific with occasional vague language. Practitioner could still act on it. |
| 3 | Mix of specific and generic. Uses phrases like "implement best practices" without defining them. |
| 2 | Mostly generic. Could apply to any cloud environment or framework without modification. |
| 1 | Completely generic. No actionable specifics. |

**Red flag phrases** (automatic deduction to ≤3):
- "implement best practices"
- "as appropriate"
- "use a reputable tool"
- "ensure proper controls are in place"
- "follow your security policy"

---

### 4. Hallucination Risk (1–5)
*Did the model introduce information not in the control context or established compliance standards?*

| Score | Criteria |
|-------|----------|
| 5 | No hallucinations. All claims grounded in provided context or well-established compliance practice. |
| 4 | No clear hallucinations, but one or two claims that seem extrapolated rather than grounded. |
| 3 | One claim that appears fabricated or significantly extrapolated from the source material. |
| 2 | Multiple fabricated claims, or one that could cause real harm if followed. |
| 1 | Significant hallucination. Invented requirements, non-existent services, or fabricated audit standards. |

**What to look for:**
- Invented control sub-requirements not in the framework
- AWS services or features that don't exist (or don't do what's claimed)
- Fabricated statistics or compliance metrics (e.g., "SOC 2 requires 99.9% MFA adoption")
- Made-up audit requirements not in the actual framework

---

### 5. Audit Readiness (1–5)
*Would following this guidance actually satisfy an auditor reviewing the control?*

This dimension requires GRC expertise to score. Ask yourself: *If a team followed these steps exactly, would they pass a SOC 2 / ISO 27001 audit for this control?*

| Score | Criteria |
|-------|----------|
| 5 | Yes, unambiguously. The guidance is sound, complete, and reflects how auditors actually evaluate this control. |
| 4 | Mostly yes. Minor gaps a team could fill with common sense. |
| 3 | Probably, but there are gaps that could become findings depending on the auditor. |
| 2 | Unlikely. The guidance is missing critical elements auditors look for, or includes practices auditors flag. |
| 1 | No. Following this guidance would likely result in direct audit findings. |

---

## Critical Errors (Automatic Failure)

These errors result in an automatic **fail** regardless of other scores. Flag these immediately.

1. **Dangerous misguidance**: The response recommends a practice that would directly cause an audit finding (e.g., "shared accounts are fine for small teams")
2. **Significant hallucination**: Fabricated control requirements, non-existent services, or invented audit standards
3. **Missing mandatory element**: A clearly required item is omitted (e.g., DPA for a vendor PII question)
4. **Contradicts ground truth**: Response directly contradicts established compliance standards
5. **Off-topic with no graceful handling**: Agent tries to answer an off-topic question by hallucinating a compliance angle

---

## Launch Readiness Criteria

A prompt version is ready to ship when, across a full eval run:

| Metric | Minimum Bar |
|--------|-------------|
| Overall average score | ≥ 3.5 |
| Hallucination risk average | ≥ 4.0 |
| Factual accuracy average | ≥ 4.0 |
| Critical errors | 0 |
| "Clear-cut" cases correctly handled | 100% |
| "Edge case" cases correctly handled | ≥ 80% |

---

## Review Recording Format

Save reviews to `evals/results/human_review_YYYYMMDD.json`:

```json
{
  "eval_id": "eval-001",
  "reviewer": "your-name",
  "review_date": "2024-01-15",
  "prompt_version": "v4",
  "model": "claude-opus-4-6",
  "scores": {
    "factual_accuracy": {"score": 5, "notes": "Correctly identified JML process requirement"},
    "completeness": {"score": 4, "notes": "Missed AWS Config rule recommendation"},
    "specificity": {"score": 5, "notes": "Named specific IAM Identity Center config steps"},
    "hallucination_risk": {"score": 5, "notes": "No fabricated claims"},
    "audit_readiness": {"score": 4, "notes": "Solid but could emphasize offboarding SLA"}
  },
  "overall_score": 4.6,
  "critical_errors": [],
  "passed": true,
  "notes": "Strong response overall. Access review cadence could be more specific."
}
```

---

## Evaluator Notes

- If you're unsure about a score, default to the **lower** score and note the ambiguity
- When in doubt about a compliance claim, check the source framework documentation
- Your notes are as important as the scores — they drive prompt improvement
- If you find a new failure pattern not in the ground truth, add it to `eval_set.json`
