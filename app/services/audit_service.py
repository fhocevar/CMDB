from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def register_audit(db: Session, username: str, action: str, entity: str, details: str) -> None:
    db.add(
        AuditLog(
            username=username,
            action=action,
            entity=entity,
            details=details,
        )
    )
    db.commit()
