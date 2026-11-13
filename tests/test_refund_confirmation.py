
import os
from datetime import datetime, timedelta

os.environ.setdefault("NVIDIA_API_KEY", "test-api-key")

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Customer,
    Order,
    RefundConfirmation,
    RefundRequest,
)
from app.services.support_service import (
    prepare_refund_confirmation,
    confirm_refund_request,
)


@pytest.fixture
def db():
    """Create an isolated in-memory database for each test."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=engine)
    session = TestingSession()

    customer = Customer(
        name="Test Customer",
        email="test@example.com",
        status="active",
    )
    session.add(customer)
    session.flush()

    order = Order(
        order_number="ORD-TEST-001",
        customer_id=customer.id,
        amount_rupees=2500,
        status="delivered",
        refund_eligible=True,
    )
    session.add(order)
    session.commit()

    yield session, customer, order

    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def prepare(
    db,
    customer,
    session_id="test-session",
    amount_rupees=1000,
):
    session, _, order = db

    return prepare_refund_confirmation(
        db=session,
        customer_id=customer.id,
        session_id=session_id,
        order_number=order.order_number,
        amount_rupees=amount_rupees,
        reason="Damaged item",
    )


def confirm(
    db,
    customer,
    confirmation_id,
    session_id="test-session",
):
    session, _, _ = db

    return confirm_refund_request(
        db=session,
        customer_id=customer.id,
        session_id=session_id,
        confirmation_id=confirmation_id,
    )


def test_preparation_creates_pending_confirmation(db):
    _, customer, _ = db

    result = prepare(db, customer)

    assert result["status"] == "pending_confirmation"

    confirmation = db[0].get(
        RefundConfirmation,
        result["confirmation_id"],
    )

    assert confirmation is not None
    assert confirmation.status == "pending_confirmation"
    assert confirmation.amount_rupees == 1000


def test_expired_confirmation_is_rejected(db):
    _, customer, _ = db
    session = db[0]

    result = prepare(db, customer)

    confirmation = session.get(
        RefundConfirmation,
        result["confirmation_id"],
    )

    confirmation.expires_at = datetime.now() - timedelta(minutes=1)
    session.commit()

    with pytest.raises(ValueError, match="expired"):
        confirm(db, customer, confirmation.id)

    refunds = session.scalars(select(RefundRequest)).all()
    assert refunds == []

    session.refresh(confirmation)
    assert confirmation.status == "expired"


def test_confirmation_cannot_be_replayed(db):
    _, customer, _ = db

    result = prepare(db, customer)
    confirmation_id = result["confirmation_id"]

    first_result = confirm(db, customer, confirmation_id)

    assert first_result["status"] == "pending"

    with pytest.raises(ValueError, match="no longer pending"):
        confirm(db, customer, confirmation_id)

    refunds = db[0].scalars(select(RefundRequest)).all()
    assert len(refunds) == 1


def test_confirmation_from_another_session_is_rejected(db):
    _, customer, _ = db

    result = prepare(
        db,
        customer,
        session_id="session-A",
    )

    with pytest.raises(ValueError, match="not found"):
        confirm(
            db,
            customer,
            result["confirmation_id"],
            session_id="session-B",
        )

    refunds = db[0].scalars(select(RefundRequest)).all()
    assert refunds == []


def test_ineligible_order_is_rejected_at_preparation(db):
    _, customer, order = db

    order.refund_eligible = False
    db[0].commit()

    with pytest.raises(ValueError, match="not eligible"):
        prepare(db, customer)

    confirmations = db[0].scalars(
        select(RefundConfirmation)
    ).all()

    assert confirmations == []


def test_amount_cannot_exceed_order_value(db):
    _, customer, order = db
    session = db[0]

    with pytest.raises(ValueError, match="exceeds the order amount"):
        prepare_refund_confirmation(
            db=session,
            customer_id=customer.id,
            session_id="test-session",
            order_number=order.order_number,
            amount_rupees=order.amount_rupees + 1,
            reason="Damaged item",
        )

    confirmations = session.scalars(
        select(RefundConfirmation)
    ).all()

    assert confirmations == []


def test_confirmation_requires_positive_amount(db):
    _, customer, order = db

    with pytest.raises(ValueError, match="positive integer"):
        prepare_refund_confirmation(
            db=db[0],
            customer_id=customer.id,
            session_id="test-session",
            order_number=order.order_number,
            amount_rupees=0,
            reason="Damaged item",
        )

    confirmations = db[0].scalars(
        select(RefundConfirmation)
    ).all()

    assert confirmations == []


def test_confirmation_is_superseded_by_new_preparation(db):
    _, customer, _ = db
    session = db[0]

    first = prepare(db, customer)
    second = prepare(db, customer)

    first_confirmation = session.get(
        RefundConfirmation,
        first["confirmation_id"],
    )
    second_confirmation = session.get(
        RefundConfirmation,
        second["confirmation_id"],
    )

    assert first_confirmation.status == "superseded"
    assert second_confirmation.status == "pending_confirmation"

    with pytest.raises(ValueError, match="no longer pending"):
        confirm(db, customer, first_confirmation.id)

    assert session.scalars(select(RefundRequest)).all() == []


def test_large_refund_requires_human_approval(db):
    _, customer, _ = db

    # The order is worth ₹10,000 for this test.
    session = db[0]
    order = db[2]
    order.amount_rupees = 10000
    session.commit()

    result = prepare(
        db,
        customer,
        amount_rupees=6000,
    )

    submitted = confirm(
        db,
        customer,
        result["confirmation_id"],
    )

    assert submitted["status"] == "awaiting_approval"

    refund = session.get(RefundRequest, submitted["id"])
    assert refund is not None
    assert refund.status == "awaiting_approval"
