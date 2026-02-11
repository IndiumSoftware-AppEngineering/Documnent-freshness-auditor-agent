"""
REST API module for the calculator service.

Endpoints:
    POST /calculate  — perform a calculation
    GET  /health     — health check

Note: The /history endpoint was removed in v2.0 but
      is still documented in openapi.yaml.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Calculator API", version="2.1.0")


class CalcRequest(BaseModel):
    """Request body for calculation."""

    operation: str
    a: float
    b: float
    precision: int = 2


class CalcResponse(BaseModel):
    """Response body for calculation."""

    result: float
    operation: str


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/calculate", response_model=CalcResponse)
def calculate(req: CalcRequest):
    """Perform an arithmetic operation.

    Args:
        req: The calculation request containing operation, a, and b.

    Returns:
        CalcResponse with the result.
    """
    ops = {
        "add": lambda: req.a + req.b,
        "subtract": lambda: req.a - req.b,
        "multiply": lambda: round(req.a * req.b, req.precision),
        "divide": lambda: req.a / req.b if req.b != 0 else (_ for _ in ()).throw(
            HTTPException(400, "Division by zero")
        ),
    }
    if req.operation not in ops:
        raise HTTPException(400, f"Unknown operation: {req.operation}")
    return CalcResponse(result=ops[req.operation](), operation=req.operation)


@app.post("/power")
def power_endpoint(base: float, exponent: float):
    """Compute power. Added in v2.1 — NOT in openapi.yaml yet."""
    return {"result": base**exponent}


@app.post("/batch")
def batch_calculate(requests: list[CalcRequest]):
    """Batch calculation endpoint. Added in v2.1 — NOT in openapi.yaml yet."""
    results = []
    for r in requests:
        results.append(calculate(r))
    return {"results": results}
