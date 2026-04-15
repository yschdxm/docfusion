from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.document import TemplateUsageEvent

router = APIRouter()


@router.get('/stats/template-usage')
async def template_usage_stats(
    limit: int = Query(default=10, ge=1, le=50),
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(
            TemplateUsageEvent.template_id,
            TemplateUsageEvent.template_name,
            func.count(TemplateUsageEvent.id).label('usage_count'),
        )
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
