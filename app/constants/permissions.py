PAYMENT_CREATE_SELF = "payment.create.self"
PAYMENT_CREATE_ANY = "payment.create.any"
PAYMENT_VIEW_SELF = "payment.view.self"
PAYMENT_VIEW_CREATED = "payment.view.created"
PAYMENT_VIEW_ALL = "payment.view.all"
PAYMENT_EDIT_REJECTED_SELF = "payment.edit.rejected_self"
PAYMENT_EDIT_REJECTED_CREATED = "payment.edit.rejected_created"
PAYMENT_APPROVE = "payment.approve"
PAYMENT_REJECT = "payment.reject"
PAYMENT_REVERSE = "payment.reverse"
PAYMENT_EXPORT = "payment.export"
USER_CREATE = "user.create"
USER_VIEW = "user.view"
USER_EDIT = "user.edit"
USER_BLOCK = "user.block"
USER_DELETE = "user.delete"
EXPENSE_VIEW_SUMMARY = "expense.view.summary"
EXPENSE_VIEW_DETAILS = "expense.view.details"
EXPENSE_CREATE = "expense.create"
FUND_VIEW = "fund.view"
FUND_ADJUST = "fund.adjust"
SETTINGS_EDIT = "settings.edit"
AUDIT_VIEW = "audit.view"
ANNOUNCEMENT_MANAGE = "announcement.manage.all"

PERMISSION_DEFINITIONS = {
    value: tuple(value.split("."))
    for name, value in list(globals().items())
    if name.isupper() and isinstance(value, str) and "." in value
}

ROLE_PERMISSION_CODES = {
    "ADMIN": set(PERMISSION_DEFINITIONS),
    "COMMITTEE": {
        PAYMENT_CREATE_ANY,
        PAYMENT_VIEW_ALL,
        PAYMENT_EDIT_REJECTED_CREATED,
        USER_CREATE,
        USER_VIEW,
        EXPENSE_VIEW_SUMMARY,
        FUND_VIEW,
    },
    "MEMBER": {
        PAYMENT_CREATE_SELF,
        PAYMENT_VIEW_SELF,
        PAYMENT_EDIT_REJECTED_SELF,
        EXPENSE_VIEW_SUMMARY,
    },
}
