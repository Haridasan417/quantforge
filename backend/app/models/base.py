from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model.

    Alembic's env.py imports Base.metadata from here so
    `alembic revision --autogenerate` can see every model below.
    """
