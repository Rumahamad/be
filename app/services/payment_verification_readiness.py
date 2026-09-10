from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.payments import Payment


def ready_payment():
    """Submission completion is durable and specific to the payment revision."""
    return select(AuditLog.id).where(
        AuditLog.entity_type == "payment",
        AuditLog.entity_id == Payment.id,
        AuditLog.action == "payment.ready_for_review",
        AuditLog.after_data["revision"].as_integer() == Payment.current_revision,
    ).exists()
