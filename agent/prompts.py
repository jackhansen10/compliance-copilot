"""
Prompt templates for the compliance copilot agent.

Design philosophy:
- Each prompt version is explicitly named and documented
- Changes are tracked with rationale (this IS the eval/iteration log)
- Prompts are structured to minimize hallucination on specific control details
- Output schema is enforced via structured instructions, validated via Pydantic

Prompt versioning strategy:
  v1: Baseline — simple instruction, no structure enforcement
  v2: Added explicit output schema + "only use provided context" constraint
  v3: Added chain-of-thought for failure pattern reasoning
  v4 (current): Added auditor persona + red flag emphasis based on eval results
"""

from dataclasses import dataclass
from typing import Optional


# ── System Prompts ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT_V1 = """
You are a compliance expert. Answer questions about security controls and how to implement them.
""".strip()

SYSTEM_PROMPT_V2 = """
You are a GRC (Governance, Risk, and Compliance) expert specializing in cloud security controls.

You help security and compliance teams understand:
- What a control requires and why it exists
- How to implement it in cloud environments (especially AWS)
- What evidence auditors typically expect
- Common implementation failures to avoid

Rules:
- Only use the control context provided. Do not invent control requirements or evidence types.
- If the context does not contain enough information to answer, say so explicitly.
- Be concrete and specific. Avoid vague guidance like "implement best practices."
- Format your response as valid JSON matching the requested schema.
""".strip()

SYSTEM_PROMPT_V3 = """
You are a GRC expert and former Big 4 auditor specializing in cloud security compliance.

You help teams implement and evidence security controls across SOC 2, ISO 27001, NIST CSF, HIPAA, and PCI DSS.

When answering, reason step by step:
1. What is the control actually testing for?
2. What does a mature implementation look like in this environment?
3. Where do teams typically fail, and why?
4. What would make an auditor flag this as a finding?

Rules:
- Ground your answer in the provided control context only. Do not introduce requirements not present in the context.
- If something is ambiguous, say so and explain the ambiguity.
- Be specific: name services, configuration settings, and artifact names.
- Format your response as valid JSON matching the requested schema.
""".strip()

# Current production prompt
SYSTEM_PROMPT_V4 = """
You are a GRC expert and former Big 4 auditor specializing in cloud security compliance (SOC 2, ISO 27001, NIST CSF, HIPAA, PCI DSS).

You help security engineers, compliance managers, and GRC teams:
- Understand what a control actually requires (and the intent behind it)
- Implement controls correctly in cloud environments
- Collect the right evidence the first time
- Avoid the mistakes that turn into audit findings

Approach every question as if you're preparing a team for their audit next quarter.
Think like an auditor reviewing their work: What would you question? What gaps would you flag?

Strict rules:
- Use ONLY the control context provided. Do not introduce requirements, services, or evidence types not in the context.
- If the context is insufficient to answer confidently, explicitly state what's missing.
- Be concrete: name specific AWS services, IAM policies, Config rules, or artifact names.
- Never say "implement best practices" without specifying what those practices are.
- Format your response as valid JSON exactly matching the schema below.
""".strip()

ACTIVE_SYSTEM_PROMPT = SYSTEM_PROMPT_V4
ACTIVE_SYSTEM_PROMPT_VERSION = "v4"


# ── Query Prompt Templates ─────────────────────────────────────────────────────

def build_control_guidance_prompt(
    control_context: dict,
    user_question: str,
    environment: Optional[str] = "AWS",
) -> str:
    """
    Build the user-turn prompt for a control guidance query.

    Args:
        control_context: The control dict from controls.json
        user_question: The user's free-form question
        environment: Cloud environment context (AWS, GCP, Azure, hybrid)
    """
    return f"""
## Control Context

**Framework:** {control_context.get('framework')}
**Control ID:** {control_context.get('control_id')}
**Title:** {control_context.get('title')}
**Description:** {control_context.get('description')}

**Key Requirements:**
{chr(10).join(f"- {r}" for r in control_context.get('key_requirements', []))}

**Typical Evidence:**
{chr(10).join(f"- {e}" for e in control_context.get('common_evidence', []))}

**AWS Implementation Guidance:**
Services: {', '.join(control_context.get('aws_implementation', {}).get('primary_services', []))}
{control_context.get('aws_implementation', {}).get('guidance', '')}

**Common Failures:**
{chr(10).join(f"- {f}" for f in control_context.get('common_failures', []))}

**Auditor Red Flags:**
{chr(10).join(f"- {r}" for r in control_context.get('auditor_red_flags', []))}

---

## User Question

{user_question}

**Environment:** {environment}

---

## Required Response Schema

Respond with a JSON object matching this exact schema:

{{
  "control_summary": "string — 2-3 sentence plain-language explanation of what this control requires and why it exists",
  "direct_answer": "string — specific answer to the user's question",
  "implementation_steps": ["string", "..."],  // ordered, concrete steps for this environment
  "evidence_to_collect": [
    {{
      "artifact": "string — name of the artifact",
      "description": "string — what it proves and how to obtain it",
      "collection_method": "string — manual | automated | tool-assisted"
    }}
  ],
  "common_pitfalls": ["string", "..."],  // specific to this control + environment
  "auditor_perspective": "string — what an auditor would look for and what would concern them",
  "confidence": "high | medium | low",  // based on how well the context covers the question
  "context_gaps": "string | null"  // anything the context didn't cover that the user should know
}}
""".strip()


def build_eval_judge_prompt(
    control_context: dict,
    user_question: str,
    agent_response: str,
    ground_truth: dict,
) -> str:
    """
    Prompt for an LLM-as-judge evaluation pass.
    Used in run_evals.py to score agent outputs against ground truth.
    """
    return f"""
You are evaluating the quality of an AI compliance agent's response.

## Control Being Asked About
Framework: {control_context.get('framework')} | Control: {control_context.get('control_id')} — {control_context.get('title')}

## User Question
{user_question}

## Agent Response
{agent_response}

## Ground Truth Reference
{ground_truth}

---

Score the agent response on each dimension from 1-5, then provide a brief rationale.

Respond with JSON:
{{
  "scores": {{
    "factual_accuracy": {{
      "score": int,  // 1-5: Does the response contain any incorrect claims about the control?
      "rationale": "string"
    }},
    "completeness": {{
      "score": int,  // 1-5: Does it address all key aspects of the question?
      "rationale": "string"
    }},
    "specificity": {{
      "score": int,  // 1-5: Are recommendations concrete (named services, settings) vs. vague?
      "rationale": "string"
    }},
    "hallucination_risk": {{
      "score": int,  // 1-5: 5=no hallucination, 1=fabricated requirements or evidence
      "rationale": "string"
    }},
    "audit_readiness": {{
      "score": int,  // 1-5: Would following this guidance actually satisfy an auditor?
      "rationale": "string"
    }}
  }},
  "overall_score": float,   // weighted average
  "critical_errors": ["string", "..."],  // any factual errors or dangerous omissions
  "strengths": ["string", "..."],
  "improvement_suggestions": ["string", "..."]
}}
""".strip()


# ── Prompt Version Registry ────────────────────────────────────────────────────
# Used by eval harness to test prompts against each other

PROMPT_VERSIONS = {
    "v1": SYSTEM_PROMPT_V1,
    "v2": SYSTEM_PROMPT_V2,
    "v3": SYSTEM_PROMPT_V3,
    "v4": SYSTEM_PROMPT_V4,
}
