"""
User ORM model.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from server.db import Base
from server.services.push_helpers import format_db_dt


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(128), nullable=True)
    full_name = Column(String(64), nullable=True)
    # admin / trader / viewer
    role = Column(String(16), nullable=False, default="trader")
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    last_login_at = Column(DateTime, nullable=True)

    def to_dict(self):
        # v10: 统一时间戳格式 "YYYY-MM-DD HH:MM:SS.fff" (rpc-field-alignment-ts-unify)
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
            "created_at": format_db_dt(self.created_at) if self.created_at else None,
            "updated_at": format_db_dt(self.updated_at) if self.updated_at else None,
            "last_login_at": format_db_dt(self.last_login_at) if self.last_login_at else None,
        }
