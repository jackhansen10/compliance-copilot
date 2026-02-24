"""
Output schemas for compliance copilot agent responses.

Using Pydantic to:
1. Validate that the LLM returned the expected structure
2. Catch hallucination signals (e.g., evidence with no collection_method)
3. Enable downstream processing (evals, UI rendering, API responses)
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CollectionMethod(str, Enum):
    MANUAL = "manual"
    AUTOMATED = "automated"
    TOOL_ASSISTED = "tool-assisted"


class EvidenceItem(BaseModel):
    artifact: str = Field(..., description="Name of the evidence artifact")
    description: str = Field(..., description="What it proves and how to obtain it")
    collection_method: CollectionMethod

    @field_validator("description")
    @classmethod
    def description_must_be_specific(cls, v: str) -> str:
        vague_phrases = ["best practices", "as appropriate", "if applicable", "various methods"]
        for phrase in vague_phrases:
            if phrase.lower() in v.lower():
                raise ValueError(
                    f"Evidence description contains vague phrase '{phrase}'. "
                    "Be specific about how to obtain this artifact."
                )
        return v


class ControlGuidanceResponse(BaseModel):
    """Structured response from the compliance guidance agent."""

    control_summary: str = Field(
        ...,
        description="2-3 sentence plain-language explanation of what the control requires and why",
        min_length=50,
    )
    direct_answer: str = Field(
        ...,
        description="Specific answer to the user's question",
        min_length=20,
    )
    implementation_steps: list[str] = Field(
        ...,
        description="Ordered, concrete implementation steps for the specified environment",
        min_length=1,
    )
    evidence_to_collect: list[EvidenceItem] = Field(
        ...,
        description="Evidence artifacts an auditor would expect",
        min_length=1,
    )
    common_pitfalls: list[str] = Field(
        ...,
        description="Common implementation failures specific to this control and environment",
        min_length=1,
    )
    auditor_perspective: str = Field(
        ...,
        description="What an auditor would look for and what would concern them",
        min_length=30,
    )
    confidence: ConfidenceLevel
    context_gaps: Optional[str] = Field(
        None,
        description="Anything the context didn't cover that the user should investigate further",
    )

    @field_validator("implementation_steps")
    @classmethod
    def steps_must_be_concrete(cls, v: list[str]) -> list[str]:
        for step in v:
            if len(step) < 15:
                raise ValueError(f"Implementation step too vague: '{step}'")
        return v


class EvalScore(BaseModel):
    score: int = Field(..., ge=1, le=5)
    rationale: str


class EvalScores(BaseModel):
    factual_accuracy: EvalScore
    completeness: EvalScore
    specificity: EvalScore
    hallucination_risk: EvalScore
    audit_readiness: EvalScore


class EvalResult(BaseModel):
    """Output from the LLM-as-judge evaluation pass."""

    scores: EvalScores
    overall_score: float = Field(..., ge=1.0, le=5.0)
    critical_errors: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Whether this response meets the minimum quality bar for shipping."""
        return (
            self.overall_score >= 3.5
            and self.scores.hallucination_risk.score >= 4
            and self.scores.factual_accuracy.score >= 4
            and len(self.critical_errors) == 0
        )
