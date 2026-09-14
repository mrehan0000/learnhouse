"""Course access requests.

Lets a signed-in user who is locked out of a restricted course ask for
access instead of hitting a dead end. Approval is granted by adding the
requester to a usergroup dedicated to that course -- reusing the exact
same usergroup/UserGroupResource mechanism every other restricted-access
grant in this codebase already goes through (see
``services/courses/lock_usergroups.py`` and ``services/courses/locks.py``),
so once approved the user unlocks through the normal access-check path
with no special-casing anywhere else.
"""

from datetime import datetime
import logging
from uuid import uuid4

from fastapi import HTTPException, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.course_access_requests import (
    AccessRequestStatus,
    CourseAccessRequest,
    CourseAccessRequestRead,
)
from src.db.courses.courses import Course
from src.db.organizations import Organization
from src.db.user_organizations import UserOrganization
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.users import PublicUser, User
from src.security.org_auth import is_org_admin
from src.security.rbac.constants import ADMIN_ROLE_ID
from src.security.auth import resolve_acting_user_id
from src.services.email.utils import send_email

logger = logging.getLogger(__name__)


async def _load_course_by_uuid(course_uuid: str, db_session: AsyncSession) -> Course:
    course = (await db_session.execute(
        select(Course).where(Course.course_uuid == course_uuid)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


async def _org_admin_emails(org_id: int, db_session: AsyncSession) -> list[str]:
    rows = (await db_session.execute(
        select(User.email)
        .join(UserOrganization, UserOrganization.user_id == User.id)
        .where(
            UserOrganization.org_id == org_id,
            UserOrganization.role_id == ADMIN_ROLE_ID,
        )
    )).all()
    return [email for (email,) in rows if email]


async def request_course_access(
    request: Request,
    course_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> CourseAccessRequestRead:
    acting_user_id = resolve_acting_user_id(current_user)
    course = await _load_course_by_uuid(course_uuid, db_session)

    existing = (await db_session.execute(
        select(CourseAccessRequest).where(
            CourseAccessRequest.course_id == course.id,
            CourseAccessRequest.user_id == acting_user_id,
        )
    )).scalars().first()

    now = str(datetime.now())
    if existing:
        if existing.status == AccessRequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have a pending request for this course",
            )
        if existing.status == AccessRequestStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have access to this course",
            )
        # Previously rejected -- a re-request reopens the same row rather
        # than accumulating a new one per attempt (course_id, user_id) is
        # unique.
        existing.status = AccessRequestStatus.PENDING
        existing.decided_by_id = None
        existing.update_date = now
        db_session.add(existing)
        await db_session.commit()
        await db_session.refresh(existing)
        access_request = existing
    else:
        access_request = CourseAccessRequest(
            status=AccessRequestStatus.PENDING,
            course_id=course.id if course.id is not None else 0,
            user_id=acting_user_id,
            org_id=course.org_id,
            creation_date=now,
            update_date=now,
        )
        db_session.add(access_request)
        await db_session.commit()
        await db_session.refresh(access_request)

    # Best-effort notification -- a delivery hiccup shouldn't fail the
    # request itself, the admin will still see it in the pending list.
    try:
        admin_emails = await _org_admin_emails(course.org_id, db_session)
        requester = (await db_session.execute(
            select(User).where(User.id == acting_user_id)
        )).scalars().first()
        requester_label = requester.email if requester else f"user #{acting_user_id}"
        for admin_email in admin_emails:
            send_email(
                to=admin_email,
                subject=f"Access request: {course.name}",
                body=(
                    f"<p>{requester_label} has requested access to "
                    f"<strong>{course.name}</strong>.</p>"
                    f"<p>Review it from the course access requests page in the dashboard.</p>"
                ),
            )
    except Exception:
        logger.exception(
            "Failed to send access-request notification for course %s", course.course_uuid
        )

    return CourseAccessRequestRead(
        id=access_request.id,
        status=access_request.status,
        course_id=access_request.course_id,
        user_id=access_request.user_id,
        org_id=access_request.org_id,
        decided_by_id=access_request.decided_by_id,
        creation_date=access_request.creation_date,
        update_date=access_request.update_date,
    )


async def _require_org_admin(user_id: int, org_id: int, db_session: AsyncSession) -> None:
    if not await is_org_admin(user_id, org_id, db_session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an organization admin can review access requests",
        )


async def list_access_requests(
    org_id: int,
    current_user: PublicUser,
    db_session: AsyncSession,
    status_filter: AccessRequestStatus | None = AccessRequestStatus.PENDING,
) -> list[CourseAccessRequestRead]:
    acting_user_id = resolve_acting_user_id(current_user)
    await _require_org_admin(acting_user_id, org_id, db_session)

    statement = (
        select(CourseAccessRequest, User.email, User.username, Course.name)
        .join(User, User.id == CourseAccessRequest.user_id)
        .join(Course, Course.id == CourseAccessRequest.course_id)
        .where(CourseAccessRequest.org_id == org_id)
        .order_by(CourseAccessRequest.creation_date.desc())
    )
    if status_filter is not None:
        statement = statement.where(CourseAccessRequest.status == status_filter)

    rows = (await db_session.execute(statement)).all()
    return [
        CourseAccessRequestRead(
            id=req.id,
            status=req.status,
            course_id=req.course_id,
            user_id=req.user_id,
            org_id=req.org_id,
            decided_by_id=req.decided_by_id,
            creation_date=req.creation_date,
            update_date=req.update_date,
            user_email=email,
            user_username=username,
            course_name=course_name,
        )
        for req, email, username, course_name in rows
    ]


_ACCESS_REQUEST_USERGROUP_NAME = "Approved: {name}"


async def _course_access_usergroup(
    course: Course, db_session: AsyncSession
) -> UserGroup:
    """The usergroup that grants access to this course via an approved
    request. Always one this feature owns -- NEVER reuses an arbitrary
    pre-existing usergroup already linked to the course (e.g. "DF Employees"
    or "Admin"). A course can have several usergroups attached for unrelated
    reasons, and any of those may also grant access to many other resources;
    adding an approved requester to one of those would silently over-grant
    them access to everything else that group touches, not just this course.
    Identifies "its own" group by an exact name match plus a live link back
    to this course, so repeat approvals for the same course reuse the same
    dedicated group instead of creating a new one each time."""
    marker_name = _ACCESS_REQUEST_USERGROUP_NAME.format(name=course.name)[:255]
    existing = (await db_session.execute(
        select(UserGroup).where(
            UserGroup.org_id == course.org_id,
            UserGroup.name == marker_name,
        )
    )).scalars().first()
    if existing:
        still_linked = (await db_session.execute(
            select(UserGroupResource).where(
                UserGroupResource.usergroup_id == existing.id,
                UserGroupResource.resource_uuid == course.course_uuid,
            )
        )).scalars().first()
        if still_linked:
            return existing

    now = str(datetime.now())
    usergroup = UserGroup(
        name=marker_name,
        description=(
            f"Auto-created by the access-request feature for {course.name}. "
            "Only ever linked to this one course -- do not reuse for anything else."
        ),
        org_id=course.org_id,
        usergroup_uuid=f"usergroup_{uuid4()}",
        creation_date=now,
        update_date=now,
    )
    db_session.add(usergroup)
    await db_session.commit()
    await db_session.refresh(usergroup)

    link = UserGroupResource(
        usergroup_id=usergroup.id if usergroup.id is not None else 0,
        resource_uuid=course.course_uuid,
        org_id=course.org_id,
        creation_date=now,
        update_date=now,
    )
    db_session.add(link)
    await db_session.commit()
    return usergroup


async def approve_access_request(
    request_id: int,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> CourseAccessRequestRead:
    acting_user_id = resolve_acting_user_id(current_user)
    access_request = (await db_session.execute(
        select(CourseAccessRequest).where(CourseAccessRequest.id == request_id)
    )).scalars().first()
    if not access_request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    await _require_org_admin(acting_user_id, access_request.org_id, db_session)

    if access_request.status != AccessRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This request has already been decided",
        )

    course = (await db_session.execute(
        select(Course).where(Course.id == access_request.course_id)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    usergroup = await _course_access_usergroup(course, db_session)

    already_member = (await db_session.execute(
        select(UserGroupUser).where(
            UserGroupUser.usergroup_id == usergroup.id,
            UserGroupUser.user_id == access_request.user_id,
        )
    )).scalars().first()
    if not already_member:
        now = str(datetime.now())
        db_session.add(UserGroupUser(
            usergroup_id=usergroup.id if usergroup.id is not None else 0,
            user_id=access_request.user_id,
            org_id=course.org_id,
            creation_date=now,
            update_date=now,
        ))

    access_request.status = AccessRequestStatus.APPROVED
    access_request.decided_by_id = acting_user_id
    access_request.update_date = str(datetime.now())
    db_session.add(access_request)
    await db_session.commit()
    await db_session.refresh(access_request)

    try:
        requester = (await db_session.execute(
            select(User).where(User.id == access_request.user_id)
        )).scalars().first()
        if requester and requester.email:
            send_email(
                to=requester.email,
                subject=f"Access approved: {course.name}",
                body=f"<p>Your request to access <strong>{course.name}</strong> has been approved. You can now open the course.</p>",
            )
    except Exception:
        logger.exception("Failed to send access-approved notification for request %s", request_id)

    return CourseAccessRequestRead(
        id=access_request.id,
        status=access_request.status,
        course_id=access_request.course_id,
        user_id=access_request.user_id,
        org_id=access_request.org_id,
        decided_by_id=access_request.decided_by_id,
        creation_date=access_request.creation_date,
        update_date=access_request.update_date,
    )


async def reject_access_request(
    request_id: int,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> CourseAccessRequestRead:
    acting_user_id = resolve_acting_user_id(current_user)
    access_request = (await db_session.execute(
        select(CourseAccessRequest).where(CourseAccessRequest.id == request_id)
    )).scalars().first()
    if not access_request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    await _require_org_admin(acting_user_id, access_request.org_id, db_session)

    if access_request.status != AccessRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This request has already been decided",
        )

    access_request.status = AccessRequestStatus.REJECTED
    access_request.decided_by_id = acting_user_id
    access_request.update_date = str(datetime.now())
    db_session.add(access_request)
    await db_session.commit()
    await db_session.refresh(access_request)

    return CourseAccessRequestRead(
        id=access_request.id,
        status=access_request.status,
        course_id=access_request.course_id,
        user_id=access_request.user_id,
        org_id=access_request.org_id,
        decided_by_id=access_request.decided_by_id,
        creation_date=access_request.creation_date,
        update_date=access_request.update_date,
    )
