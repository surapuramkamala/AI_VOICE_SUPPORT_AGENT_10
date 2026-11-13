from fastapi import Depends, FastAPI, HTTPException, Request
from openai import APIError
from sqlalchemy.orm import Session
from app.voice_api import router as voice_router
#from app.database import get_db
from app.database import Base, engine, get_db
from app.models import Customer, UserAccount
from app.schemas import (
    AgentChatRequest,
    CustomerResponse,
    OrderResponse,
    RefundRequestCreate,
)
from app.security import install_security_controls
from app.services.support_service import (
    decide_refund,
    get_customer,
    get_customer_orders,
)
from app.services.support_tools import (
    get_customer_details,
    check_customer_orders,
    prepare_customer_refund,
    confirm_customer_refund,
)
from app.agent.nvidia_agent import chat_with_agent
from pathlib import Path
import logging
import os
from sqlalchemy import select
from app.auth import (
    TOKEN_TTL_SECONDS, create_access_token, get_current_account,
    get_current_customer_id, require_reviewer, verify_password,
)
from app.security_schemas import LoginRequest, TokenResponse, ReviewerDecisionRequest

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="AI Voice Support Agent API",
    version="0.1.0",
)
install_security_controls(app)
#added newly
@app.on_event("startup")
def initialize_database():
    Base.metadata.create_all(bind=engine)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)
@app.get("/voice-ui", include_in_schema=False)
def voice_ui():
    return FileResponse(STATIC_DIR / "index.html")
app.include_router(voice_router)
@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply browser-facing hardening headers to API and UI responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    if os.getenv("APP_ENV", "development").lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.post("/auth/login", response_model=TokenResponse, tags=["Authentication"])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate an account and issue a short-lived bearer token."""
    email = payload.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    account = db.scalar(select(UserAccount).where(UserAccount.email == email))
    # Perform a password hash even for unknown emails to reduce timing differences.
    dummy_hash = "pbkdf2_sha256$310000$MDEyMzQ1Njc4OWFiY2RlZg==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    password_hash = account.password_hash if account else dummy_hash
    valid_password = verify_password(payload.password, password_hash)
    if account is None or not valid_password or not account.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if account.role == "customer":
        customer = get_customer(db, account.customer_id) if account.customer_id else None
        if customer is None or customer.status != "active":
            raise HTTPException(status_code=401, detail="Invalid email or password.")
    return TokenResponse(
        access_token=create_access_token(account),
        expires_in=TOKEN_TTL_SECONDS,
        role=account.role,
    )


@app.get("/auth/me", tags=["Authentication"])
def who_am_i(account: UserAccount = Depends(get_current_account)):
    return {"email": account.email, "role": account.role, "customer_id": account.customer_id}


@app.get("/")
def health_check():
    return {
        "service": "AI Voice Support Agent",
        "status": "running",
    }


@app.get("/customers/me", response_model=CustomerResponse)
def read_customer(
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    customer = get_customer(db, customer_id)

    if customer is None or customer.status != "active":
        raise HTTPException(
            status_code=404,
            detail="Active customer not found.",
        )

    return customer


@app.get("/customers/me/orders", response_model=list[OrderResponse])
def read_customer_orders(
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    customer = get_customer(db, customer_id)

    if customer is None or customer.status != "active":
        raise HTTPException(
            status_code=404,
            detail="Active customer not found.",
        )

    return get_customer_orders(db, customer_id)


@app.get("/tools/customer-details")
def tool_customer_details(
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    result = get_customer_details(db, customer_id)

    if isinstance(result, dict) and "error" in result:
        raise HTTPException(
            status_code=404,
            detail=result["error"],
        )

    return result


@app.get("/tools/orders")
def tool_customer_orders(
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    result = check_customer_orders(db, customer_id)

    if isinstance(result, dict) and "error" in result:
        raise HTTPException(
            status_code=404,
            detail=result["error"],
        )

    return result


@app.post("/tools/refund-request")
def tool_refund_request(
    payload: RefundRequestCreate,
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    """Prepare a refund for customer confirmation; do not submit it yet."""
    customer = get_customer(db, customer_id)

    if customer is None or customer.status != "active":
        raise HTTPException(
            status_code=404,
            detail="Active customer not found.",
        )

    result = prepare_customer_refund(
        db=db,
        customer_id=customer_id,
        session_id="api-refund-request",
        order_number=payload.order_number,
        amount_rupees=payload.amount_rupees,
        reason=payload.reason,
    )

    if isinstance(result, dict) and "error" in result:
        raise HTTPException(
            status_code=400,
            detail=result["error"],
        )

    return result


@app.post("/refunds")
def request_refund():
    """Direct refund submission is disabled to prevent confirmation bypass."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Direct refund submission is disabled. "
            "Use the refund confirmation workflow through /agent/chat."
        ),
    )


@app.post("/reviewer/refunds/{refund_id}/decision", tags=["Refund Review"])
def reviewer_refund_decision(
    refund_id: int,
    payload: ReviewerDecisionRequest,
    reviewer_account: UserAccount = Depends(require_reviewer),
    db: Session = Depends(get_db),
):
    """Record a refund decision using the authenticated reviewer identity."""
    try:
        return decide_refund(
            db=db,
            refund_id=refund_id,
            reviewer=reviewer_account.email,
            decision=payload.decision,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agent/chat")
def agent_chat(
    payload: AgentChatRequest,
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    customer = get_customer(db, customer_id)

    if customer is None or customer.status != "active":
        raise HTTPException(
            status_code=404,
            detail="Active customer not found.",
        )

    try:
        answer = chat_with_agent(
            message=payload.message,
            db=db,
            customer_id=customer_id,
            session_id=payload.session_id,
        )

        return {"response": answer}

    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "NVIDIA model request failed. Check your API key, "
                "model availability, and API limits."
            ),
        ) from exc
