from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (registers tables)
from .config import db_path

_engine = None
_engine_path = None

SEED_USERS = [
    ("u_admin_rc", "Alice Admin", "administrator", "riverside"),
    ("u_bom_rc", "Bob Business-Office", "business_office_manager", "riverside"),
    ("u_don_rc", "Dana DON", "don", "riverside"),
    ("u_cfo", "Chris CFO", "cfo", "portfolio"),
    ("u_owner", "Olivia Owner", "owner", "portfolio"),
]


def get_engine():
    global _engine, _engine_path
    path = db_path()
    if _engine is None or _engine_path != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        _engine_path = path
    return _engine


@contextmanager
def get_session():
    with Session(get_engine()) as session:
        yield session


def reset_db() -> None:
    """Drop and recreate every table, then seed users."""
    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        for uid, name, role, building in SEED_USERS:
            s.add(models.User(id=uid, name=name, role=role, building_id=building))
        s.commit()
