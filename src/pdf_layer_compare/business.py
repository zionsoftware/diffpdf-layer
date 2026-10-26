"""Workflow decisions, separate from the PDF content comparison."""
from .model import BODY, UNLAYERED, ROLES, BusinessStatus, PairSummary, Status, layer_key


def aggregate(statuses):
    statuses = list(statuses)
    if Status.DIFFERENT in statuses:
        return Status.DIFFERENT
    if not statuses or Status.UNKNOWN in statuses:
        return Status.UNKNOWN
    return Status.MATCH


def summarize(left, right, left_role, right_role, rows):
    earlier = min(ROLES.index(left_role), ROLES.index(right_role))
    required = [BODY, UNLAYERED, *(layer_key(r) for r in ROLES[:earlier + 1])]
    allowed = [layer_key(r) for r in ROLES[earlier + 1:]]
    indexed = {row.component: row for row in rows}
    required += [name for name in indexed if name not in required and name not in allowed]
    reasons, states = [], []
    for name in required:
        row = indexed.get(name)
        state = row.status if row else Status.UNKNOWN
        states.append(state)
        if state != Status.MATCH:
            reasons.append(f"{name}: {state}" + (f" / {row.detail}" if row and row.detail else " / 必須項目を確認できません" if row is None else ""))
    state = aggregate(states)
    business = {Status.MATCH: BusinessStatus.PASS, Status.DIFFERENT: BusinessStatus.FAIL,
                Status.UNKNOWN: BusinessStatus.UNKNOWN}[state]
    return PairSummary(left, right, aggregate(r.status for r in rows), business, required, allowed, reasons,
                       left_role, right_role)
