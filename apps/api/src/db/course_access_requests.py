from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import ForeignKey, Column, Integer, UniqueConstraint


class AccessRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CourseAccessRequest(SQLModel, table=True):
    __table_args__ = (
        # A user can have at most one row per course; re-requesting after a
        # rejection updates the existing row back to PENDING rather than
        # inserting a second one.
        UniqueConstraint("course_id", "user_id", name="uq_access_request_course_user"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    status: AccessRequestStatus = Field(default=AccessRequestStatus.PENDING)
    course_id: int = Field(
        sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), index=True)
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), index=True)
    )
    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"))
    )
    decided_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )
    creation_date: str
    update_date: str


class CourseAccessRequestRead(SQLModel):
    id: int
    status: AccessRequestStatus
    course_id: int
    user_id: int
    org_id: int
    decided_by_id: Optional[int] = None
    creation_date: str
    update_date: str
    # Denormalized for the admin review list, so the frontend doesn't need a
    # separate round trip per row to show who's asking and for what.
    user_email: Optional[str] = None
    user_username: Optional[str] = None
    course_name: Optional[str] = None
