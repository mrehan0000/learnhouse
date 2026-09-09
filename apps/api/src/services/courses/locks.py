"""Lock-based access checks for chapters and activities.

Mirrors the Playground access-type pattern but keyed on chapter_uuid /
activity_uuid in ``usergroupresource``. Lock tiers:

- ``public``:        anyone, including anonymous, can read
- ``authenticated``: must be signed in
- ``restricted``:    must be in an assigned usergroup (or an org admin)

Batch helpers are provided for TOC-style reads where many resources need
to be checked at once without N+1 queries.
"""

from typing import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.course_chapters import CourseChapter
from src.db.trail_steps import TrailStep
from src.db.user_organizations import UserOrganization
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.users import AnonymousUser, APITokenUser, PublicUser
from src.security.auth import resolve_acting_user_id
from src.security.rbac.constants import ADMIN_OR_MAINTAINER_ROLE_IDS


async def is_org_admin(user_id: int, org_id: int, db_session: AsyncSession) -> bool:
    """True if user is admin/maintainer on this org (bypasses all locks)."""
    uo = (await db_session.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.org_id == org_id,
        )
    )).scalars().first()
    return bool(uo and uo.role_id in ADMIN_OR_MAINTAINER_ROLE_IDS)


async def batch_accessible_restricted_uuids(
    user_id: int,
    resource_uuids: Iterable[str],
    db_session: AsyncSession,
) -> set[str]:
    """Return the subset of resource_uuids the user can access via usergroup."""
    uuids = [u for u in resource_uuids if u]
    if not uuids:
        return set()

    ugrs = (await db_session.execute(
        select(
            UserGroupResource.resource_uuid,
            UserGroupResource.usergroup_id,
        ).where(UserGroupResource.resource_uuid.in_(uuids))
    )).all()
    if not ugrs:
        return set()

    ug_ids = list({row[1] for row in ugrs})
    member_ug_ids = set(
        (await db_session.execute(
            select(UserGroupUser.usergroup_id).where(
                UserGroupUser.usergroup_id.in_(ug_ids),
                UserGroupUser.user_id == user_id,
            )
        )).scalars().all()
    )
    return {resource_uuid for resource_uuid, ug_id in ugrs if ug_id in member_ug_ids}


async def is_locked_for_user(
    lock_type: str | None,
    resource_uuid: str,
    org_id: int,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: AsyncSession,
    *,
    accessible_restricted_uuids: set[str] | None = None,
    is_admin: bool | None = None,
) -> bool:
    """True if the resource should be hidden from current_user.

    ``accessible_restricted_uuids`` and ``is_admin`` are pre-computed escape
    hatches for batch callers -- they avoid repeating the same queries for
    every row. When absent, this function resolves them on its own.
    """
    lt = (lock_type or "public").lower()
    if lt == "public":
        return False

    is_anon = isinstance(current_user, AnonymousUser)
    if lt == "authenticated":
        return is_anon

    if lt != "restricted":
        # Unknown value -- fail safe (treat as public to avoid accidentally
        # locking people out after a rename/migration mishap).
        return False

    if is_anon:
        return True

    acting_user_id = resolve_acting_user_id(current_user)
    admin = is_admin if is_admin is not None else await is_org_admin(acting_user_id, org_id, db_session)
    if admin:
        return False

    if accessible_restricted_uuids is not None:
        return resource_uuid not in accessible_restricted_uuids

    accessible = await batch_accessible_restricted_uuids(
        acting_user_id, [resource_uuid], db_session
    )
    return resource_uuid not in accessible


async def is_locked_by_incomplete_prerequisites(
    course_id: int,
    activity_id: int,
    user_id: int,
    db_session: AsyncSession,
) -> bool:
    """True if an earlier activity in the course is not yet completed.

    "Earlier" is resolved from CourseChapter.order (chapter position within
    the course) then ChapterActivity.order (activity position within its
    chapter) -- ordering lives on the join rows, not on Chapter/Activity
    themselves, since the same resource can be reused elsewhere in a
    different position.

    Callers are expected to already have checked
    ``course.enforce_sequential_progression`` and admin/anonymous status;
    this function only resolves the ordering + completion check.
    """
    this_link = (await db_session.execute(
        select(ChapterActivity.chapter_id, ChapterActivity.order).where(
            ChapterActivity.course_id == course_id,
            ChapterActivity.activity_id == activity_id,
        )
    )).first()
    if this_link is None:
        # Not linked into this course's chapters -- nothing to sequence
        # against, fail open rather than lock something we can't place.
        return False
    this_chapter_id, this_activity_order = this_link

    chapter_orders = dict((await db_session.execute(
        select(CourseChapter.chapter_id, CourseChapter.order).where(
            CourseChapter.course_id == course_id
        )
    )).all())
    this_chapter_order = chapter_orders.get(this_chapter_id)
    if this_chapter_order is None:
        return False

    all_links = (await db_session.execute(
        select(
            ChapterActivity.activity_id,
            ChapterActivity.chapter_id,
            ChapterActivity.order,
        ).where(ChapterActivity.course_id == course_id)
    )).all()

    prerequisite_ids = [
        act_id
        for act_id, chap_id, act_order in all_links
        if act_id != activity_id
        and chapter_orders.get(chap_id) is not None
        and (
            chapter_orders[chap_id] < this_chapter_order
            or (
                chapter_orders[chap_id] == this_chapter_order
                and act_order < this_activity_order
            )
        )
    ]
    if not prerequisite_ids:
        return False

    completed_ids = set((await db_session.execute(
        select(TrailStep.activity_id).where(
            TrailStep.course_id == course_id,
            TrailStep.user_id == user_id,
            TrailStep.activity_id.in_(prerequisite_ids),
            TrailStep.complete.is_(True),
        )
    )).scalars().all())

    return not set(prerequisite_ids).issubset(completed_ids)
