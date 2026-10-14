"""Payment processing for the demo shop."""
import logging

from database import DatabaseConnectionTimeout

logger = logging.getLogger("PaymentService")


class PaymentService:
    def __init__(self, db):
        self.db = db

    def charge(self, order_id, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        query = "UPDATE orders SET status = 'PAID', amount = %s WHERE id = %s"
        try:
            result = self.db.execute(query, (amount, order_id))
        except DatabaseConnectionTimeout:
            logger.error("Database connection timeout while charging order=%s (waited 5.0s)", order_id)
            raise
        logger.info("Charge succeeded order=%s amount=%.2f", order_id, amount)
        return result

    def refund(self, order_id):
        query = "UPDATE orders SET status = 'REFUNDED' WHERE id = %s"
        return self.db.execute(query, (order_id,))
