
# from sqlalchemy import select

# from app.database import Base, SessionLocal, engine
# from app.models import Customer, Order


# def initialize_database():
#     Base.metadata.create_all(bind=engine)

#     with SessionLocal() as db:
#         existing_customer = db.scalar(
#             select(Customer).where(Customer.email == "maya@example.com")
#         )

#         if existing_customer:
#             print("Sample data already exists.")
#             return

#         # customer1 = Customer(
#         #     name="Maya Sharma",
#         #     email="maya@example.com",
#         #     status="active",
#         # )

#         # customer2 = Customer(
#         #     name="Arjun Rao",
#         #     email="arjun@example.com",
#         #     status="active",
#         # )

#         customer3 = Customer(
#             name="Rakshitha Sevela",
#             email="rakshitha@gmail.com",
#             status="active"
#         )

#         db.add_all([customer3])
#         db.flush()

#         orders = [
#             Order(
#                 order_number="ORD-3001",
#                 customer_id=customer3.id,
#                 amount_rupees=3500,
#                 status="shipped",
#                 refund_eligible=True,
#             ),
#             Order(
#                 order_number="ORD-3002",
#                 customer_id=customer3.id,
#                 amount_rupees=5500,
#                 status="delivered",
#                 refund_eligible=True,
#             )
#         ]

#         db.add_all(orders)
#         db.commit()

#     print("Database initialized and sample data inserted.")


# if __name__ == "__main__":
#     initialize_database()
#----------------------------------------------------------------------
from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Customer, Order


def initialize_database():
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        email = "customer1@gmail.com"

        customer = db.scalar(
            select(Customer).where(Customer.email == email)
        )

        if customer is None:
            customer = Customer(
                name="Customer1 5",
                email=email,
                status="active",
            )
            db.add(customer)
            db.flush()
            print(f"Customer created with ID: {customer.id}")
        else:
            print(f"Customer already exists with ID: {customer.id}")

        order_data = [
            ("ORD-6001", 3400, "shipped", True),
            ("ORD-6002", 5700, "delivered", True),
        ]

        for number, amount, status, eligible in order_data:
            existing_order = db.scalar(
                select(Order).where(
                    Order.order_number == number
                )
            )

            if existing_order is None:
                db.add(
                    Order(
                        order_number=number,
                        customer_id=customer.id,
                        amount_rupees=amount,
                        status=status,
                        refund_eligible=eligible,
                    )
                )

        db.commit()
        print("Database initialization completed.")


if __name__ == "__main__":
    initialize_database()