"""Checkout flow: validates an order and charges it."""
from database import DatabaseConnectionTimeout
from payment_service import PaymentService


class CheckoutError(Exception):
    """Raised when a checkout cannot be completed."""


class CheckoutService:
    def __init__(self, payments: PaymentService):
        self.payments = payments

    def process_checkout(self, order):
        currency = order["currency"]
        try:
            self.payments.charge(order["id"], order["total"])
        except DatabaseConnectionTimeout as exc:
            raise CheckoutError(
                f"Payment could not be completed for order {order['id']}"
            ) from exc
        return {"status": "confirmed", "order": order["id"], "currency": currency}
