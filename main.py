"""
FastAPI wrapper for the compliance copilot agent.

Exposes:
  GET  /controls              — list available controls
  POST /query                 — ask a compliance question
  GET  /health                — health check
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

from agent.agent import ComplianceCopilot
from agent.schemas import ControlGuidanceResponse

app = FastAPI(
    title="Compliance Copilot",
    description="AI-powered GRC guidance agent for security controls",
    version="0.1.0",
)

# Single agent instance (in production: use dependency injection + connection pool)
_agent: ComplianceCopilot | None = None


def get_agent() -> ComplianceCopilot:
    global _agent
    if _agent is None:
        _agent = ComplianceCopilot()
    return _agent


class QueryRequest(BaseModel):
    control_query: str
    question: str
    environment: Optional[str] = "AWS"


class QueryResponse(BaseModel):
    guidance: ControlGuidanceResponse
    metadata: dict


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/controls")
def list_controls():
    return get_agent().list_controls()


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    try:
        response, metadata = get_agent().query(
            control_query=request.control_query,
            user_question=request.question,
            environment=request.environment,
        )
        # Don't expose raw_response in API output
        metadata.pop("raw_response", None)
        return QueryResponse(guidance=response, metadata=metadata)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
