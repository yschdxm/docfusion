from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.db.postgres import get_db
from app.models.document import TemplateUsageEvent
from app.models.user import User

settings = get_settings()
router = APIRouter()


@router.get('/stats/template-usage')
async def template_usage_stats(
    limit: int = Query(default=10, ge=1, le=50),
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 用户过滤：包含无主数据或仅自己的数据
    if settings.INCLUDE_ORPHAN_DATA:
        user_filter = or_(
            TemplateUsageEvent.user_id == current_user.id,
            TemplateUsageEvent.user_id.is_(None)
        )
    else:
        user_filter = TemplateUsageEvent.user_id == current_user.id

    stmt = (
        select(
            TemplateUsageEvent.template_id,
            TemplateUsageEvent.template_name,
            func.count(TemplateUsageEvent.id).label('usage_count'),
        )
        .where(user_filter)
        .group_by(TemplateUsageEvent.template_id, TemplateUsageEvent.template_name)
        .order_by(func.count(TemplateUsageEvent.id).desc(), TemplateUsageEvent.template_name.asc())
        .limit(limit)
    )

    if start is not None:
        stmt = stmt.where(TemplateUsageEvent.used_at >= start)
    if end is not None:
        stmt = stmt.where(TemplateUsageEvent.used_at <= end)

    rows = (await db.execute(stmt)).all()
    total_usage = sum(int(row.usage_count or 0) for row in rows)

    return {
        'total_usage': total_usage,
        'items': [
            {
                'template_id': str(row.template_id),
                'template_name': row.template_name,
                'usage_count': int(row.usage_count or 0),
            }
            for row in rows
        ],
    }
