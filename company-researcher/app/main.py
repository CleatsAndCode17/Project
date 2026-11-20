"""FastAPI application for Company Researcher Chat."""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import CompanyResearcherAgent
from app.security import RateLimiter

# Load environment configuration
load_dotenv()

# Setup logging (avoid logging sensitive keys or raw tracebacks to users)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("company_researcher")

app = FastAPI(
    title="Company Researcher Chat",
    description="AI agent web application that researches company websites and answers grounded questions.",
    version="1.0.0",
)

# CORS: Default to same-origin only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # Empty list restricts cross-origin requests by default
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Rate limiter setup
rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
rate_limiter = RateLimiter(limit_per_minute=rate_limit_per_minute)

# Agent setup
agent = CompanyResearcherAgent()

# Static directories
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# Request / Response Schemas
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    company: Optional[str] = None


class ResetRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)


class ResetResponse(BaseModel):
    status: str = "reset"


class HealthResponse(BaseModel):
    status: str
    model: str
    configured: bool


# Helper to extract client IP
def get_client_ip(request: Request) -> str:
    """Extract client IP from request headers or socket."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


# Global Exception Handler (Never expose raw stack traces to the user)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again later."},
    )


# API Endpoints
@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, request: Request):
    """Chat endpoint for company research and follow-up questions."""
    # 1. Enforce message length <= 2000 chars
    if len(payload.message) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message exceeds maximum allowed length of 2000 characters.",
        )

    # 2. Rate limiting check per client IP
    client_ip = get_client_ip(request)
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please wait a minute before sending more messages.",
        )

    # 3. Process message through agent
    try:
        reply, company = await agent.process_message(
            session_id=payload.session_id,
            message=payload.message,
        )
        return ChatResponse(reply=reply, company=company)
    except Exception as exc:
        logger.error("Error processing agent message: %s", exc)
        return ChatResponse(
            reply="An error occurred while researching this company. Please try again.",
            company=None,
        )


@app.post("/api/reset", response_model=ResetResponse)
async def reset_endpoint(payload: ResetRequest):
    """Clear conversation history and stored website data for session_id."""
    agent.reset_session(payload.session_id)
    return ResetResponse(status="reset")


@app.get("/api/health", response_model=HealthResponse)
async def health_endpoint():
    """Health check endpoint exposing service and model status."""
    return HealthResponse(
        status="ok",
        model=agent.model_name,
        configured=bool(agent.api_key),
    )


# Static Files & UI Serving
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_index():
    """Serve the single-page chat frontend."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"status": "UI files not found"}, status_code=404)
