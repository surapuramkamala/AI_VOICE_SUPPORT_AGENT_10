
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Boolean
)
from sqlalchemy.orm import relationship
from app.database import Base
from sqlalchemy.orm import relationship


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    status = Column(String(20), default="active", nullable=False)

    orders = relationship("Order", back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(30), unique=True, index=True, nullable=False)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )
    amount_rupees = Column(Integer, nullable=False)
    status = Column(String(30), default="processing", nullable=False)
    refund_eligible = Column(Boolean, default=True, nullable=False)

    customer = relationship("Customer", back_populates="orders")
    refunds = relationship("RefundRequest", back_populates="order")


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    __table_args__ = (
        CheckConstraint("amount_rupees > 0", name="positive_refund_amount"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer,
        ForeignKey("orders.id"),
        nullable=False,
        index=True,
    )
    amount_rupees = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)
    status = Column(String(30), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    order = relationship("Order", back_populates="refunds")
    approval = relationship(
        "Approval",
        back_populates="refund",
        uselist=False,
    )


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    refund_request_id = Column(
        Integer,
        ForeignKey("refund_requests.id"),
        unique=True,
        nullable=False,
    )
    reviewer = Column(String(100), nullable=False)
    decision = Column(String(20), nullable=False)
    comment = Column(String(500), nullable=True)
    decided_at = Column(DateTime, default=datetime.now, nullable=False)

    refund = relationship("RefundRequest", back_populates="approval")
    
class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        index=True,
        nullable=False,
    )
    role = Column(String(20), nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

class RefundConfirmation(Base):
    __tablename__ = "refund_confirmations"

  
    id = Column(Integer, primary_key=True, index=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )

    session_id = Column(String(100), nullable=False, index=True)

    order_id = Column(
        Integer,
        ForeignKey("orders.id"),
        nullable=False,
    )

    amount_rupees = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)

    status = Column(
        String(30),
        nullable=False,
        default="pending_confirmation",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )

    expires_at = Column(DateTime, nullable=False)

    order = relationship("Order")


class UserAccount(Base):
    """Login identity separate from customer profile and reviewer identity."""
    __tablename__ = "voice_user_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # customer or reviewer
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
