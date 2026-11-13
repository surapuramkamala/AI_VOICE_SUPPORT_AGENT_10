import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Customer, Order
from app.services.support_tools import (
    check_customer_orders,
    get_customer_details,
)


@pytest.fixture
def db(tmp_path):
    """Create isolated test data; never use the developer's local database."""
    database_path = tmp_path / "support_tools_test.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        active = Customer(
            name="Active Test Customer",
            email="active-tools-test@example.com",
            status="active",
        )
        inactive = Customer(
            name="Inactive Test Customer",
            email="inactive-tools-test@example.com",
            status="inactive",
        )
        session.add_all([active, inactive])
        session.flush()
        session.add(
            Order(
                order_number="ORD-TOOLS-001",
                customer_id=active.id,
                amount_rupees=2500,
                status="delivered",
                refund_eligible=True,
            )
        )
        session.commit()
        active_id, inactive_id = active.id, inactive.id

    yield TestingSessionLocal, active_id, inactive_id
    engine.dispose()


def test_get_customer_details_returns_active_customer(db):
    SessionLocal, active_id, _ = db
    with SessionLocal() as session:
        result = get_customer_details(session, active_id)
    assert result == {
        "id": active_id,
        "name": "Active Test Customer",
        "email": "active-tools-test@example.com",
    }


@pytest.mark.parametrize("which", ["missing", "inactive"])
def test_get_customer_details_rejects_missing_or_inactive_customer(db, which):
    SessionLocal, _, inactive_id = db
    customer_id = 999999 if which == "missing" else inactive_id
    with SessionLocal() as session:
        result = get_customer_details(session, customer_id)
    assert result == {"error": "Active customer not found."}


def test_check_customer_orders_returns_order_fields(db):
    SessionLocal, active_id, _ = db
    with SessionLocal() as session:
        result = check_customer_orders(session, active_id)
    assert result == [
        {
            "order_number": "ORD-TOOLS-001",
            "amount_rupees": 2500,
            "status": "delivered",
            "refund_eligible": True,
        }
    ]


def test_check_customer_orders_rejects_inactive_customer(db):
    SessionLocal, _, inactive_id = db
    with SessionLocal() as session:
        result = check_customer_orders(session, inactive_id)
    assert result == {"error": "Active customer not found."}
