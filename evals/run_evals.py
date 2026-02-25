"""
Evaluation harness for the compliance copilot agent.

Runs the eval dataset against the agent and scores outputs using:
1. LLM-as-judge (automated scoring via judge prompt)
2. Ground truth rule-based checks (must_include / must_not_include)
3. Schema validation (Pydantic)

Results are saved to evals/results/ with full metadata for tracking
across prompt versions and model changes.

Usage:
    # Run full eval suite with current (active) prompt
    python -m evals.run_evals

    # Compare two prompt versions head-to-head
    python -m evals.run_evals --compare v3 v4

    # Run single eval case
    python -m evals.run_evals --eval-id eval-001
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from pydantic import ValidationError

from agent.agent import ComplianceCopilot
from agent.prompts import build_eval_judge_prompt
from agent.schemas import EvalResult, ControlGuidanceResponse


EVALS_DIR = Path(__file__).parent
RESULTS_DIR = EVALS_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_eval_set(eval_id: str | None = None) -> list[dict]:
    with open(EVALS_DIR / "eval_set.json") as f:
        evals = json.load(f)
    if eval_id:
        return [e for e in evals if e["eval_id"] == eval_id]
    return evals


def run_agent(
    eval_case: dict,
    prompt_version: str | None = None,
) -> tuple[ControlGuidanceResponse | None, dict]:
    """Run a single eval case through the agent."""
    agent = ComplianceCopilot(prompt_version=prompt_version)
    try:
        response, metadata = agent.query(
            control_query=eval_case["control_id"],
            user_question=eval_case["user_question"],
            environment=eval_case.get("environment", "AWS"),
        )
        return response, metadata
    except Exception as e:
        return None, {"error": str(e), "prompt_version": prompt_version or "active"}


def run_ground_truth_checks(
    response: ControlGuidanceResponse,
    ground_truth: dict,
) -> dict:
    """
    Rule-based checks against ground truth must_include / must_not_include.
    These are deterministic checks that don't require an LLM.
    """
    response_text = json.dumps(response.model_dump()).lower()

    must_include_results = []
    for item in ground_truth.get("must_include", []):
        # Simple keyword check — in production, use semantic similarity
        found = any(word.lower() in response_text for word in item.split() if len(word) > 4)
        must_include_results.append({"item": item, "found": found})

    must_not_include_results = []
    for item in ground_truth.get("must_not_include", []):
        # Violation only if the full forbidden phrase appears (avoids false positives
        # when the response correctly rejects the idea, e.g. "shared accounts are not acceptable")
        found = item.lower() in response_text
        must_not_include_results.append({"item": item, "found": found})

    required_services = ground_truth.get("key_aws_services", [])
    services_mentioned = [s for s in required_services if s.lower() in response_text]

    return {
        "must_include": must_include_results,
        "must_not_include": must_not_include_results,
        "must_include_pass_rate": sum(r["found"] for r in must_include_results) / max(len(must_include_results), 1),
        "must_not_include_violations": [r["item"] for r in must_not_include_results if r["found"]],
        "required_services_mentioned": services_mentioned,
        "required_services_coverage": len(services_mentioned) / max(len(required_services), 1),
    }


def run_llm_judge(
    eval_case: dict,
    response: ControlGuidanceResponse,
    metadata: dict,
) -> EvalResult | None:
    """Run LLM-as-judge scoring on an agent response."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Load the control context for the judge
    from agent.agent import load_controls, find_control
    controls = load_controls()
    control = find_control(eval_case["control_id"], controls)

    judge_prompt = build_eval_judge_prompt(
        control_context=control,
        user_question=eval_case["user_question"],
        agent_response=json.dumps(response.model_dump(), indent=2),
        ground_truth=eval_case["ground_truth"],
    )

    try:
        message = client.messages.create(
            model="claude-opus-4-6",  # Use the strongest model for judging
            max_tokens=1024,
            messages=[{"role": "user", "content": judge_prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return EvalResult(**json.loads(raw.strip()))
    except Exception as e:
        print(f"LLM judge failed: {e}")
        return None


def run_eval_suite(
    prompt_version: str | None = None,
    eval_id: str | None = None,
    verbose: bool = True,
) -> dict:
    """
    Run the full eval suite and return aggregated results.
    """
    eval_cases = load_eval_set(eval_id)
    results = []
    # Use timezone-aware UTC timestamps to avoid deprecation warnings
    timestamp = datetime.now(UTC).isoformat()

    print(f"\n{'='*60}")
    print(f"Running {len(eval_cases)} eval cases")
    print(f"Prompt version: {prompt_version or 'active'}")
    print(f"{'='*60}\n")

    for case in eval_cases:
        print(f"[{case['eval_id']}] {case['control_id']} — {case['difficulty']}")

        response, metadata = run_agent(case, prompt_version)

        result = {
            "eval_id": case["eval_id"],
            "control_id": case["control_id"],
            "difficulty": case["difficulty"],
            "tags": case["tags"],
            "prompt_version": metadata.get("prompt_version"),
            "model": metadata.get("model"),
            "timestamp": timestamp,
            "error": metadata.get("error"),
        }

        if response is None:
            result["status"] = "error"
            print(f"  ❌ Error: {metadata.get('error')}")
        else:
            # Ground truth checks
            gt_checks = run_ground_truth_checks(response, case["ground_truth"])
            result["ground_truth_checks"] = gt_checks

            # LLM judge
            eval_result = run_llm_judge(case, response, metadata)
            if eval_result:
                result["llm_judge"] = eval_result.model_dump()
                result["passed"] = eval_result.passed and len(gt_checks["must_not_include_violations"]) == 0
            else:
                result["passed"] = None

            result["status"] = "pass" if result.get("passed") else "fail"
            status_emoji = "✅" if result["status"] == "pass" else "❌"
            score_str = f"{eval_result.overall_score:.1f}/5.0" if eval_result else "N/A"
            print(f"  {status_emoji} Score: {score_str} | GT pass rate: {gt_checks['must_include_pass_rate']:.0%}")

            if gt_checks["must_not_include_violations"]:
                print(f"  ⚠️  Violations: {gt_checks['must_not_include_violations']}")

            if verbose and eval_result and eval_result.critical_errors:
                print(f"  🚨 Critical errors: {eval_result.critical_errors}")

        results.append(result)

    # Aggregate stats
    completed = [r for r in results if r["status"] != "error"]
    passed = [r for r in completed if r.get("passed")]
    llm_scores = [r["llm_judge"]["overall_score"] for r in completed if r.get("llm_judge")]

    summary = {
        "run_timestamp": timestamp,
        "prompt_version": prompt_version or "active",
        "total": len(results),
        "passed": len(passed),
        "failed": len(completed) - len(passed),
        "errors": len(results) - len(completed),
        "pass_rate": len(passed) / max(len(completed), 1),
        "avg_llm_score": sum(llm_scores) / len(llm_scores) if llm_scores else None,
        "meets_launch_criteria": (
            len(llm_scores) > 0
            and sum(llm_scores) / len(llm_scores) >= 3.5
            and all(len(r.get("ground_truth_checks", {}).get("must_not_include_violations", [])) == 0 for r in completed)
        ),
        "results": results,
    }

    # Save results
    filename = f"eval_run_{prompt_version or 'active'}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    output_path = RESULTS_DIR / filename
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Results: {len(passed)}/{len(completed)} passed ({summary['pass_rate']:.0%})")
    if summary["avg_llm_score"]:
        print(f"Avg LLM score: {summary['avg_llm_score']:.2f}/5.0")
    print(f"Launch criteria met: {'✅ YES' if summary['meets_launch_criteria'] else '❌ NO'}")
    print(f"Full results: {output_path}")
    print(f"{'='*60}\n")

    return summary


def compare_prompt_versions(version_a: str, version_b: str) -> None:
    """Run the full eval suite for two prompt versions and print a comparison."""
    print(f"\n🔬 Comparing prompt versions: {version_a} vs {version_b}\n")
    results_a = run_eval_suite(prompt_version=version_a, verbose=False)
    results_b = run_eval_suite(prompt_version=version_b, verbose=False)

    print(f"\n{'='*60}")
    print(f"HEAD-TO-HEAD: {version_a} vs {version_b}")
    print(f"{'='*60}")
    print(f"{'Metric':<30} {version_a:>10} {version_b:>10}")
    print(f"{'-'*50}")
    print(f"{'Pass Rate':<30} {results_a['pass_rate']:>10.0%} {results_b['pass_rate']:>10.0%}")
    if results_a['avg_llm_score'] and results_b['avg_llm_score']:
        print(f"{'Avg LLM Score':<30} {results_a['avg_llm_score']:>10.2f} {results_b['avg_llm_score']:>10.2f}")
    print(f"{'Launch Ready':<30} {str(results_a['meets_launch_criteria']):>10} {str(results_b['meets_launch_criteria']):>10}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run compliance copilot evaluations")
    parser.add_argument("--compare", nargs=2, metavar=("VERSION_A", "VERSION_B"),
                        help="Compare two prompt versions head-to-head")
    parser.add_argument("--prompt-version", help="Specific prompt version to test (default: active)")
    parser.add_argument("--eval-id", help="Run a single eval case by ID")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    if args.compare:
        compare_prompt_versions(args.compare[0], args.compare[1])
    else:
        run_eval_suite(
            prompt_version=args.prompt_version,
            eval_id=args.eval_id,
            verbose=args.verbose,
        )
