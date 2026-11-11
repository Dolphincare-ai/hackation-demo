"""Who may resolve, approve, or confirm a settings change. Generic."""
from ..config import get_config
from ..models import Task, User


class Forbidden(PermissionError):
    pass


def can_act_on_task(user: User, task: Task) -> bool:
    # The task's role, or the owner (top of every escalation ladder).
    return user.role == task.role or user.role == "owner"


def require_task(user: User | None, task: Task) -> None:
    if user is None:
        raise Forbidden("Unknown user")
    if not can_act_on_task(user, task):
        raise Forbidden(f"This step belongs to the {task.role.replace('_', ' ')}")


def require_change(user: User | None, scope: str, keys: list[str]) -> None:
    """scope: once | always."""
    if user is None:
        raise Forbidden("Unknown user")
    rules = get_config()["change_permissions"]
    if user.role not in rules[scope]:
        who = ", ".join(r.replace("_", " ") for r in rules[scope])
        raise Forbidden(f"Only {who} can confirm {'a standing change' if scope == 'always' else 'this change'}")
    owner_only = [k for k in keys if any(k == p or k.startswith(p + ".") for p in rules["owner_only"])]
    if owner_only and user.role != "owner":
        raise Forbidden(f"Only the owner can change {', '.join(owner_only)}")
