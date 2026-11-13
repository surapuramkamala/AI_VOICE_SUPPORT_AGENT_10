
from sqlalchemy.orm import Session

from app.services.support_service import (
    get_customer,
    get_customer_orders,
    prepare_refund_confirmation,
    confirm_refund_request,
)


def get_customer_details(db: Session, customer_id: int):
    customer = get_customer(db, customer_id)

    if customer is None or customer.status != "active":
        return {"error": "Active customer not found."}

    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
    }


def check_customer_orders(db: Session, customer_id: int):
    customer = get_customer(db, customer_id)

    if customer is None or customer.status != "active":
        return {"error": "Active customer not found."}

    orders = get_customer_orders(db, customer_id)

    return [
        {
            "order_number": order.order_number,
            "amount_rupees": order.amount_rupees,
            "status": order.status,
            "refund_eligible": bool(order.refund_eligible),
        }
        for order in orders
    ]


def prepare_customer_refund(
    db: Session,
    customer_id: int,
    session_id: str,
    order_number: str,
    amount_rupees: int,
    reason: str,
):
    try:
        return prepare_refund_confirmation(
            db=db,
            customer_id=customer_id,
            session_id=session_id,
            order_number=order_number,
            amount_rupees=amount_rupees,
            reason=reason,
        )
    except ValueError as exc:
        return {"error": str(exc)}


def confirm_customer_refund(
    db: Session,
    customer_id: int,
    session_id: str,
    confirmation_id: int,
):
    try:
        return confirm_refund_request(
            db=db,
            customer_id=customer_id,
            session_id=session_id,
            confirmation_id=confirmation_id,
        )
    except ValueError as exc:
        return {"error": str(exc)}