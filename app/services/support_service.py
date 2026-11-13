
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Approval,
    Customer,
    Order,
    RefundConfirmation,
    RefundRequest,
)


# Demo configuration only.
REFUND_APPROVAL_THRESHOLD_RUPEES = 5000

# These statuses reserve part of an order's refundable balance.
ACTIVE_REFUND_STATUSES = [
    "pending",
    "awaiting_approval",
    "approved_pending_execution",
    "completed",
]


def get_customer(db: Session, customer_id: int):
    return db.scalar(
        select(Customer).where(Customer.id == customer_id)
    )


def get_customer_orders(db: Session, customer_id: int):
    return db.scalars(
        select(Order)
        .where(Order.customer_id == customer_id)
        .order_by(Order.id)
    ).all()


def get_order_for_customer(
    db: Session,
    customer_id: int,
    order_number: str,
):
    return db.scalar(
        select(Order).where(
            Order.customer_id == customer_id,
            Order.order_number == order_number,
        )
    )


def _validate_refund_inputs(
    amount_rupees: int,
    order_number: str,
    reason: str,
):
    if type(amount_rupees) is not int or amount_rupees <= 0:
        raise ValueError(
            "Refund amount must be a positive integer in rupees."
        )

    if not order_number or not order_number.strip():
        raise ValueError("Order number is required.")

    if not reason or not reason.strip():
        raise ValueError("Refund reason is required.")


def _validate_order_for_refund(
    db: Session,
    customer_id: int,
    order_number: str,
    amount_rupees: int,
):
    order = get_order_for_customer(
        db=db,
        customer_id=customer_id,
        order_number=order_number.strip(),
    )

    if order is None:
        raise ValueError("Order not found for this customer.")

    if order.refund_eligible not in (True, 1):
        raise ValueError("This order is not eligible for a refund.")

    if order.status not in {"delivered", "shipped"}:
        raise ValueError(
            "The order status does not permit a refund request."
        )

    if amount_rupees > order.amount_rupees:
        raise ValueError("Refund amount exceeds the order amount.")

    return order


def _get_remaining_refundable_balance(
    db: Session,
    order: Order,
) -> int:
    previous_refunds = db.scalars(
        select(RefundRequest).where(
            RefundRequest.order_id == order.id,
            RefundRequest.status.in_(ACTIVE_REFUND_STATUSES),
        )
    ).all()

    already_requested = sum(
        refund.amount_rupees for refund in previous_refunds
    )

    return order.amount_rupees - already_requested


def _refund_status(amount_rupees: int) -> str:
    if amount_rupees > REFUND_APPROVAL_THRESHOLD_RUPEES:
        return "awaiting_approval"

    return "pending"


def create_refund_request(
    db: Session,
    customer_id: int,
    order_number: str,
    amount_rupees: int,
    reason: str,
):
    """
    Create a refund request after backend validation.

    This function does not execute a payment or refund.
    For customer-facing agent requests, use the confirmation flow.
    """

    _validate_refund_inputs(
        amount_rupees,
        order_number,
        reason,
    )

    try:
        # Acquire a write lock on the order before checking the balance.
        # The no-op UPDATE helps serialize writes on SQLite.
        order = db.scalar(
            select(Order).where(
                Order.customer_id == customer_id,
                Order.order_number == order_number.strip(),
            )
        )

        if order is None:
            raise ValueError("Order not found for this customer.")

        db.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(amount_rupees=Order.amount_rupees)
            .execution_options(synchronize_session=False)
        )
        db.expire(order)

        order = _validate_order_for_refund(
            db=db,
            customer_id=customer_id,
            order_number=order_number,
            amount_rupees=amount_rupees,
        )

        remaining = _get_remaining_refundable_balance(db, order)

        if remaining <= 0:
            raise ValueError(
                "No refundable balance remains for this order."
            )

        if amount_rupees > remaining:
            raise ValueError(
                "Requested amount exceeds the remaining refundable "
                f"balance of ₹{remaining}."
            )

        status = _refund_status(amount_rupees)

        refund = RefundRequest(
            order_id=order.id,
            amount_rupees=amount_rupees,
            reason=reason.strip(),
            status=status,
        )

        db.add(refund)
        db.commit()
        db.refresh(refund)

        return {
            "id": refund.id,
            "order_number": order.order_number,
            "amount_rupees": refund.amount_rupees,
            "status": refund.status,
            "message": (
                "Refund request requires human approval."
                if status == "awaiting_approval"
                else (
                    "Refund request created. "
                    "Payment execution has not occurred."
                )
            ),
        }

    except Exception:
        db.rollback()
        raise


def prepare_refund_confirmation(
    db: Session,
    customer_id: int,
    session_id: str,
    order_number: str,
    amount_rupees: int,
    reason: str,
):
    """Validate refund details and prepare a short-lived confirmation."""

    if not session_id or not session_id.strip():
        raise ValueError("A valid session ID is required.")

    if len(session_id) > 100:
        raise ValueError("Session ID is too long.")

    _validate_refund_inputs(
        amount_rupees,
        order_number,
        reason,
    )

    try:
        order = _validate_order_for_refund(
            db=db,
            customer_id=customer_id,
            order_number=order_number,
            amount_rupees=amount_rupees,
        )

        # Serialize writes for this order before checking its balance.
        db.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(amount_rupees=Order.amount_rupees)
            .execution_options(synchronize_session=False)
        )
        db.expire(order)

        order = _validate_order_for_refund(
            db=db,
            customer_id=customer_id,
            order_number=order_number,
            amount_rupees=amount_rupees,
        )

        remaining = _get_remaining_refundable_balance(db, order)

        if remaining <= 0 or amount_rupees > remaining:
            raise ValueError(
                f"Only ₹{max(remaining, 0)} remains refundable."
            )

        # Supersede previous pending confirmations in this session.
        pending_confirmations = db.scalars(
            select(RefundConfirmation).where(
                RefundConfirmation.customer_id == customer_id,
                RefundConfirmation.session_id == session_id,
                RefundConfirmation.status == "pending_confirmation",
            )
        ).all()

        for pending in pending_confirmations:
            pending.status = "superseded"

        now = datetime.now()

        confirmation = RefundConfirmation(
            customer_id=customer_id,
            session_id=session_id,
            order_id=order.id,
            amount_rupees=amount_rupees,
            reason=reason.strip(),
            status="pending_confirmation",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )

        db.add(confirmation)
        db.commit()
        db.refresh(confirmation)

        return {
            "confirmation_id": confirmation.id,
            "order_number": order.order_number,
            "amount_rupees": confirmation.amount_rupees,
            "reason": confirmation.reason,
            "status": confirmation.status,
            "expires_at": confirmation.expires_at.isoformat(),
            "message": (
                "Please confirm submitting a refund request for "
                f"₹{confirmation.amount_rupees} on order "
                f"{order.order_number}. Reason: {confirmation.reason}. "
                "No refund request has been submitted yet."
            ),
        }

    except Exception:
        db.rollback()
        raise


def confirm_refund_request(
    db: Session,
    customer_id: int,
    session_id: str,
    confirmation_id: int,
):
    """
    Submit a previously prepared refund after explicit confirmation.

    The refund creation and confirmation status update share one
    transaction. The model must never be the authority for confirmation.
    """

    if not session_id or not session_id.strip():
        raise ValueError("A valid session ID is required.")

    try:
        now = datetime.now()

        # Atomically claim the confirmation only if it remains pending
        # and has not expired.
        claim = db.execute(
            update(RefundConfirmation)
            .where(
                RefundConfirmation.id == confirmation_id,
                RefundConfirmation.customer_id == customer_id,
                RefundConfirmation.session_id == session_id,
                RefundConfirmation.status == "pending_confirmation",
                RefundConfirmation.expires_at > now,
            )
            .values(status="processing")
            .execution_options(synchronize_session=False)
        )

        if claim.rowcount != 1:
            db.rollback()

            confirmation = db.scalar(
                select(RefundConfirmation).where(
                    RefundConfirmation.id == confirmation_id,
                    RefundConfirmation.customer_id == customer_id,
                    RefundConfirmation.session_id == session_id,
                )
            )

            if confirmation is None:
                raise ValueError(
                    "Confirmation not found for this customer and session."
                )

            if (
                confirmation.status == "pending_confirmation"
                and datetime.now() >= confirmation.expires_at
            ):
                confirmation.status = "expired"
                db.commit()

                raise ValueError(
                    "Confirmation expired. Please prepare the refund again."
                )

            raise ValueError(
                "This confirmation is no longer pending. "
                "Prepare a new refund confirmation if needed."
            )

        db.expire_all()

        confirmation = db.scalar(
            select(RefundConfirmation).where(
                RefundConfirmation.id == confirmation_id,
                RefundConfirmation.customer_id == customer_id,
                RefundConfirmation.session_id == session_id,
            )
        )

        if confirmation is None:
            raise ValueError("Confirmation could not be verified.")

        # Verify the order belongs to this customer.
        order = db.scalar(
            select(Order).where(
                Order.id == confirmation.order_id,
                Order.customer_id == customer_id,
            )
        )

        if order is None:
            raise ValueError("The order could not be verified.")

        # Acquire a write lock on this order before checking the balance.
        db.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(amount_rupees=Order.amount_rupees)
            .execution_options(synchronize_session=False)
        )
        db.expire(order)

        order = db.scalar(
            select(Order).where(
                Order.id == confirmation.order_id,
                Order.customer_id == customer_id,
            )
        )

        if order is None:
            raise ValueError("The order could not be verified.")

        if order.refund_eligible not in (True, 1):
            raise ValueError("This order is not eligible for a refund.")

        if order.status not in {"delivered", "shipped"}:
            raise ValueError(
                "The order status does not permit a refund request."
            )

        amount = confirmation.amount_rupees

        if type(amount) is not int or amount <= 0:
            raise ValueError(
                "Refund amount must be a positive integer in rupees."
            )

        if amount > order.amount_rupees:
            raise ValueError("Refund amount exceeds the order amount.")

        if not confirmation.reason or not confirmation.reason.strip():
            raise ValueError("Refund reason is required.")

        remaining = _get_remaining_refundable_balance(db, order)

        if remaining <= 0 or amount > remaining:
            raise ValueError(
                "Requested amount exceeds the remaining refundable "
                f"balance of ₹{max(remaining, 0)}."
            )

        status = _refund_status(amount)

        refund = RefundRequest(
            order_id=order.id,
            amount_rupees=amount,
            reason=confirmation.reason.strip(),
            status=status,
        )

        db.add(refund)

        # Both database changes commit atomically.
        confirmation.status = "submitted"

        db.commit()
        db.refresh(refund)

        return {
            "id": refund.id,
            "order_number": order.order_number,
            "amount_rupees": refund.amount_rupees,
            "status": refund.status,
            "confirmation_id": confirmation.id,
            "message": (
                "Your confirmed refund request was submitted. "
                + (
                    "Human approval is required before execution."
                    if status == "awaiting_approval"
                    else "Payment execution has not occurred."
                )
            ),
        }

    except Exception:
        db.rollback()
        raise


def decide_refund(
    db: Session,
    refund_id: int,
    reviewer: str,
    decision: str,
    comment: str | None = None,
):
    """Record a human approval or rejection; do not execute payment."""

    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected.")

    if not reviewer or not reviewer.strip():
        raise ValueError("Reviewer identity is required.")

    try:
        refund = db.scalar(
            select(RefundRequest)
            .where(RefundRequest.id == refund_id)
            .with_for_update()
        )

        if refund is None:
            raise ValueError("Refund request not found.")

        if refund.status != "awaiting_approval":
            raise ValueError("Refund is not awaiting approval.")

        approval = Approval(
            refund_request_id=refund.id,
            reviewer=reviewer.strip(),
            decision=decision,
            comment=comment,
        )

        refund.status = (
            "approved_pending_execution"
            if decision == "approved"
            else "rejected"
        )

        db.add(approval)
        db.commit()
        db.refresh(refund)

        return {
            "refund_id": refund.id,
            "status": refund.status,
            "message": (
                "Approval recorded. Refund still needs authorized execution."
                if decision == "approved"
                else "Refund request rejected."
            ),
        }

    except Exception:
        db.rollback()
        raise
