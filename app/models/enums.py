import enum


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    INACTIVE = "INACTIVE"
    DELETED = "DELETED"


class PaymentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class ContributionStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class ReviewAction(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LedgerDirection(str, enum.Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class FileStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"
