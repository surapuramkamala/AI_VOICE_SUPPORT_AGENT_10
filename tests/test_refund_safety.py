
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

os.environ.setdefault("NVIDIA_API_KEY", "test-api-key")

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Approval,
    Customer,
    Order,
    RefundRequest,
)
from app.services.support_service import (
    prepare_refund_confirmation,
    confirm_refund_request,
    decide_refund,
)


@pytest.fixture
def database(tmp_path):
    """Create a file-backed SQLite database for isolated tests."""

    database_path = tmp_path / "refund_safety.db"

    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={
            "check_same_thread": False,
            "timeout": 15,
        },
    )

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        customer = Customer(
            name="Safety Test Customer",
            email="safety-test@example.com",
            status="active",
        )
        db.add(customer)
        db.flush()

        order = Order(
            order_number="ORD-SAFETY-001",
            customer_id=customer.id,
            amount_rupees=10000,
            status="delivered",
            refund_eligible=True,
        )
        db.add(order)
        db.commit()

        customer_id = customer.id
        order_number = order.order_number

    yield SessionLocal, customer_id, order_number

    engine.dispose()


def prepare_refund(
    db,
    customer_id,
    order_number,
    session_id="safety-session",
    amount=1000,
):
    return prepare_refund_confirmation(
        db=db,
        customer_id=customer_id,
        session_id=session_id,
        order_number=order_number,
        amount_rupees=amount,
        reason="Damaged item",
    )


def confirm_refund(
    db,
    customer_id,
    confirmation_id,
    session_id="safety-session",
):
    return confirm_refund_request(
        db=db,
        customer_id=customer_id,
        session_id=session_id,
        confirmation_id=confirmation_id,
    )


def test_refunds_cannot_exceed_remaining_order_balance(database):
    SessionLocal, customer_id, order_number = database

    with SessionLocal() as db:
        first = prepare_refund(
            db,
            customer_id,
            order_number,
            amount=7000,
        )

        first_result = confirm_refund(
            db,
            customer_id,
            first["confirmation_id"],
        )

        assert first_result["status"] == "awaiting_approval"

    with SessionLocal() as db:
        # ₹7,000 is already reserved by an active refund request.
        # Only ₹3,000 remains refundable from this ₹10,000 order.
        with pytest.raises(ValueError, match="Only ₹3000 remains refundable"):
            prepare_refund(
                db,
                customer_id,
                order_number,
                amount=3001,
            )

        refunds = db.scalars(select(RefundRequest)).all()
        assert len(refunds) == 1
        assert sum(r.amount_rupees for r in refunds) == 7000


def test_exact_remaining_balance_can_be_requested(database):
    SessionLocal, customer_id, order_number = database

    with SessionLocal() as db:
        first = prepare_refund(
            db,
            customer_id,
            order_number,
            amount=7000,
        )
        confirm_refund(db, customer_id, first["confirmation_id"])

    with SessionLocal() as db:
        # A refund request for the exact remaining balance is allowed.
        second = prepare_refund(
            db,
            customer_id,
            order_number,
            amount=3000,
        )

        result = confirm_refund(
            db,
            customer_id,
            second["confirmation_id"],
        )

        assert result["amount_rupees"] == 3000

        refunds = db.scalars(select(RefundRequest)).all()
        assert sum(r.amount_rupees for r in refunds) == 10000


def test_concurrent_confirmation_creates_at_most_one_refund(database):
    SessionLocal, customer_id, order_number = database

    with SessionLocal() as db:
        prepared = prepare_refund(
            db,
            customer_id,
            order_number,
            session_id="concurrent-session",
            amount=2000,
        )
        confirmation_id = prepared["confirmation_id"]

    barrier = Barrier(2)

    def submit_confirmation():
        # Each worker uses its own database session.
        with SessionLocal() as db:
            barrier.wait()

            try:
                result = confirm_refund(
                    db,
                    customer_id,
                    confirmation_id,
                    session_id="concurrent-session",
                )
                return ("success", result)

            except Exception as exc:
                # A losing concurrent attempt may be rejected by the
                # confirmation state check or by the database lock.
                return ("failure", type(exc).__name__)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(submit_confirmation),
            executor.submit(submit_confirmation),
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    with SessionLocal() as db:
        refund_count = db.scalar(
            select(func.count()).select_from(RefundRequest)
        )

        # Regardless of the outcome returned to each worker, one
        # confirmation must not create two refund requests.
        assert refund_count == 1

    assert sum(outcome[0] == "success" for outcome in outcomes) == 1


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        ("approved", "approved_pending_execution"),
        ("rejected", "rejected"),
    ],
)
def test_human_approval_and_rejection(
    database,
    decision,
    expected_status,
):
    SessionLocal, customer_id, order_number = database

    with SessionLocal() as db:
        prepared = prepare_refund(
            db,
            customer_id,
            order_number,
            amount=6000,
        )

        submitted = confirm_refund(
            db,
            customer_id,
            prepared["confirmation_id"],
        )

        assert submitted["status"] == "awaiting_approval"

        result = decide_refund(
            db=db,
            refund_id=submitted["id"],
            reviewer="authorized-reviewer",
            decision=decision,
            comment="Safety test decision",
        )

        assert result["status"] == expected_status

        refund = db.get(RefundRequest, submitted["id"])
        assert refund.status == expected_status

        approval = db.scalar(
            select(Approval).where(
                Approval.refund_request_id == submitted["id"]
            )
        )

        assert approval is not None
        assert approval.reviewer == "authorized-reviewer"
        assert approval.decision == decision

        if decision == "approved":
            # Approval does not mean payment has been executed.
            assert refund.status == "approved_pending_execution"


def test_cannot_decide_same_refund_twice(database):
    SessionLocal, customer_id, order_number = database

    with SessionLocal() as db:
        prepared = prepare_refund(
            db,
            customer_id,
            order_number,
            amount=6000,
        )
        submitted = confirm_refund(
            db,
            customer_id,
            prepared["confirmation_id"],
        )

        decide_refund(
            db,
            submitted["id"],
            reviewer="authorized-reviewer",
            decision="approved",
        )

        with pytest.raises(ValueError, match="not awaiting approval"):
            decide_refund(
                db,
                submitted["id"],
                reviewer="another-reviewer",
                decision="rejected",
            )

        approvals = db.scalars(select(Approval)).all()
        assert len(approvals) == 1
