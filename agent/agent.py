"""
Core compliance copilot agent.

Wraps Anthropic API calls with:
- Control context retrieval
- Prompt construction (versioned)
- Structured output parsing + validation
- Basic retry logic on parse failures
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

import anthropic
from pydantic import ValidationError

from agent.prompts import (
    ACTIVE_SYSTEM_PROMPT,
    ACTIVE_SYSTEM_PROMPT_VERSION,
    PROMPT_VERSIONS,
    build_control_guidance_prompt,
)
from agent.schemas import ControlGuidanceResponse

# Load .env from project root so ANTHROPIC_API_KEY is available
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ── Control Library ────────────────────────────────────────────────────────────

def load_controls() -> dict[str, dict]:
    """Load controls from the data layer, indexed by control ID."""
    controls_path = Path(__file__).parent.parent / "data" / "controls.json"
    with open(controls_path) as f:
        controls = json.load(f)
    return {c["id"]: c for c in controls}


def find_control(query: str, controls: dict[str, dict]) -> Optional[dict]:
    """
    Simple control lookup. Matches on id, control_id, or title substring.
    In production this would be a vector search over embeddings.
    """
    query_lower = query.lower().strip()

    # Exact ID match first
    if query_lower in controls:
        return controls[query_lower]

    # Match on control_id (e.g., "CC6.1")
    for control in controls.values():
        if control.get("control_id", "").lower() == query_lower:
            return control

    # Substring match on title or tags
    for control in controls.values():
        if query_lower in control.get("title", "").lower():
            return control
        if any(query_lower in tag for tag in control.get("tags", [])):
            return control

    return None


# ── Agent ──────────────────────────────────────────────────────────────────────

class ComplianceCopilot:
    """
    Main agent class. Handles:
    - Control context retrieval
    - Prompt construction
    - API calls with retry
    - Response parsing and validation
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        prompt_version: Optional[str] = None,
        max_retries: int = 2,
    ):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.controls = load_controls()
        self.max_retries = max_retries

        # Allow overriding prompt version for A/B testing in evals
        if prompt_version and prompt_version in PROMPT_VERSIONS:
            self.system_prompt = PROMPT_VERSIONS[prompt_version]
            self.prompt_version = prompt_version
        else:
            self.system_prompt = ACTIVE_SYSTEM_PROMPT
            self.prompt_version = ACTIVE_SYSTEM_PROMPT_VERSION

    def query(
        self,
        control_query: str,
        user_question: str,
        environment: str = "AWS",
    ) -> tuple[ControlGuidanceResponse, dict]:
        """
        Main query method.

        Args:
            control_query: Control ID or search term (e.g., "CC6.1" or "access control")
            user_question: The user's specific question
            environment: Cloud environment for implementation guidance

        Returns:
            (parsed_response, metadata) tuple
            metadata includes raw_response, tokens, prompt_version for eval logging
        """
        control = find_control(control_query, self.controls)
        if not control:
            raise ValueError(
                f"No control found matching '{control_query}'. "
                f"Available: {list(self.controls.keys())}"
            )

        prompt = build_control_guidance_prompt(control, user_question, environment)

        raw_response = None
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,  # Response includes long lists; 2048 caused truncation → JSON parse errors
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_response = message.content[0].text

                # Strip markdown code fences if present
                clean = raw_response.strip()
                if clean.startswith("```"):
                    clean = clean.split("```")[1]
                    if clean.startswith("json"):
                        clean = clean[4:]
                    clean = clean.strip()

                parsed_json = json.loads(clean)
                response = ControlGuidanceResponse(**parsed_json)

                metadata = {
                    "control_id": control["control_id"],
                    "framework": control["framework"],
                    "prompt_version": self.prompt_version,
                    "model": self.model,
                    "input_tokens": message.usage.input_tokens,
                    "output_tokens": message.usage.output_tokens,
                    "attempts": attempt + 1,
                    "raw_response": raw_response,
                }
                return response, metadata

            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                last_error = e
                if attempt < self.max_retries:
                    print(f"Parse attempt {attempt + 1} failed: {e}. Retrying...")
                continue

        raise RuntimeError(
            f"Failed to parse valid response after {self.max_retries + 1} attempts. "
            f"Last error: {last_error}\nRaw response: {raw_response}"
        )

    def list_controls(self) -> list[dict]:
        """Return summary of available controls."""
        return [
            {
                "id": c["id"],
                "framework": c["framework"],
                "control_id": c["control_id"],
                "title": c["title"],
                "tags": c["tags"],
            }
            for c in self.controls.values()
        ]


# ── CLI Quick Test ─────────────────────────────────────────────────────────────

def _format_response(response: ControlGuidanceResponse, meta: dict) -> str:
    """Build the full CLI output text from response and metadata."""
    lines = [
        "\n=== Compliance Copilot Response ===",
        f"Control: {meta['framework']} {meta['control_id']}",
        f"Prompt Version: {meta['prompt_version']} | Model: {meta['model']}",
        f"Tokens: {meta['input_tokens']} in / {meta['output_tokens']} out\n",
        f"Summary: {response.control_summary}\n",
        f"Answer: {response.direct_answer}\n",
        "Implementation Steps:",
    ]
    for i, step in enumerate(response.implementation_steps, 1):
        lines.append(f"  {i}. {step}")
    lines.append(f"\nConfidence: {response.confidence.value}")
    if response.context_gaps:
        lines.append(f"Context Gaps: {response.context_gaps}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Compliance Copilot agent (demo query)")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("agent_output.txt"),
        help="Write full output to this file (default: agent_output.txt)",
    )
    args = parser.parse_args()
    out_path = args.output

    agent = ComplianceCopilot()

    try:
        response, meta = agent.query(
            control_query="CC6.1",
            user_question="We're a 50-person SaaS company on AWS. We're about to go through our first SOC 2 Type II. What do we need to have in place for this control, and what evidence should we start collecting now?",
            environment="AWS",
        )
        text = _format_response(response, meta)
        out_path.write_text(text, encoding="utf-8")
        print(text)
        print(f"\n(Full output also written to {out_path})")
    except Exception as e:
        error_content = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        if "Raw response:" in str(e):
            error_content += "\n\n--- Raw API response (for debugging) ---\n"
            # RuntimeError message includes "Raw response: ..." at the end
            raw_part = str(e).split("Raw response:")[-1].strip()
            error_content += raw_part
        out_path.write_text(error_content, encoding="utf-8")
        print(error_content, file=sys.stderr)
        print(f"\nError and details written to {out_path}", file=sys.stderr)
        sys.exit(1)
