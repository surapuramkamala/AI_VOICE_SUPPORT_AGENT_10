"""Provision a customer or reviewer login from a trusted local terminal.

Examples:
  python scripts_create_user.py --email maya@example.com --role customer --customer-id 1
  python scripts_create_user.py --email reviewer@example.com --role reviewer
"""
import argparse
import getpass

from sqlalchemy import select

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Customer, UserAccount


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an application login account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=["customer", "reviewer"])
    parser.add_argument("--customer-id", type=int, default=None)
    args = parser.parse_args()
    email = args.email.strip().lower()
    if args.role == "customer" and args.customer_id is None:
        parser.error("--customer-id is required for customer accounts")
    if args.role == "reviewer" and args.customer_id is not None:
        parser.error("--customer-id is not allowed for reviewer accounts")
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        parser.error(str(exc))

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(UserAccount).where(UserAccount.email == email)):
            parser.error("An account with that email already exists")
        if args.role == "customer":
            customer = db.get(Customer, args.customer_id)
            if customer is None or customer.status != "active":
                parser.error("Customer ID does not identify an active customer")
            if db.scalar(select(UserAccount).where(UserAccount.customer_id == args.customer_id)):
                parser.error("This customer already has a login account")
        account = UserAccount(email=email, password_hash=password_hash, role=args.role, customer_id=args.customer_id)
        db.add(account)
        db.commit()
    print(f"Created {args.role} account for {email}.")


if __name__ == "__main__":
    main()
