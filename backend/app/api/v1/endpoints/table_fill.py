from datetime import datetime
from typing import List
from uuid import UUID
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import engine, get_db
from app.models.document import Document, TableFillTask, TemplateUsageEvent
from app.schemas.table_fill import TableFillRequest, TableFillResponse
from app.services.table_filling_service import table_filling_service

router = APIRouter()
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))


def _get_file_media_type(file_type: str) -> str:
    media_types = {
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ppt': 'application/vnd.ms-powerpoint',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'txt': 'text/plain; charset=utf-8',
        'md': 'text/markdown; charset=utf-8',
    }
    return media_types.get((file_type or '').lower(), 'application/octet-stream')


def _resolve_document_path(file_path: str | None) -> str | None:
    if not file_path:
        return None

    normalized = os.path.normpath(file_path)
    candidates: list[str] = []

    if os.path.isabs(normalized):
        candidates.append(normalized)
    else:
        trimmed = normalized.lstrip('.\\/')
        candidates.extend(
            [
                os.path.abspath(normalized),
                os.path.abspath(os.path.join(BACKEND_ROOT, normalized)),
                os.path.abspath(os.path.join(BACKEND_ROOT, trimmed)),
                os.path.abspath(os.path.join(PROJECT_ROOT, normalized)),
                os.path.abspath(os.path.join(PROJECT_ROOT, trimmed)),
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.exists(candidate):
            return candidate

    return candidates[0] if candidates else None


@router.post('/fill', response_model=TableFillResponse)
async def fill_table(
    request: TableFillRequest,
    db: AsyncSession = Depends(get_db),
):
    task = TableFillTask(
        template_file_id=request.template_file_id,
        source_file_ids=[str(fid) for fid in request.source_file_ids],
        user_instruction=request.user_instruction,
        status='processing',
        result={
            'progress': '0%',
            'current_step': '准备中...',
            'total_files': len(request.source_file_ids),
            'processed_files': 0,
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    async def update_progress(message: str, progress: str | None = None):
        try:
            async with AsyncSession(engine) as progress_db:
                current_result = task.result or {}
                current_result.update(
                    {
                        'current_step': message,
                        'progress': progress or current_result.get('progress', '0%'),
                        'updated_at': datetime.utcnow().isoformat(),
                    }
                )
                stmt = (
                    sql_update(TableFillTask)
                    .where(TableFillTask.id == task.id)
                    .values(result=current_result)
                )
                await progress_db.execute(stmt)
                await progress_db.commit()
        except Exception as exc:
            print(f'Progress update error: {exc}')

    try:
        await update_progress('正在加载源文档...', '10%')

        source_files = []
        for idx, file_id in enumerate(request.source_file_ids):
            result = await db.execute(select(Document).where(Document.id == file_id))
            doc = result.scalar_one_or_none()
            if not doc:
                continue
            source_files.append({'file_type': doc.file_type, 'file_path': doc.file_path})
            percent = 20 + int(((idx + 1) / max(len(request.source_file_ids), 1)) * 20)
            await update_progress(f'已加载文档 {idx + 1}/{len(request.source_file_ids)}', f'{percent}%')

        await update_progress('正在加载模板...', '40%')

        template_result = await db.execute(
            select(Document).where(Document.id == request.template_file_id)
        )
        template_doc = template_result.scalar_one_or_none()
        if not template_doc:
            raise HTTPException(status_code=404, detail='Template file not found')

        template_file = {'file_type': template_doc.file_type, 'file_path': template_doc.file_path}

        await update_progress('正在分析模板结构...', '50%')

        if template_doc.file_type == 'xlsx':
            await update_progress('正在填写 Excel 表格...', '60%')
            fill_result = await table_filling_service.fill_table(
                source_files=source_files,
                template_file=template_file,
                user_instruction=request.user_instruction,
            )
        else:
            await update_progress('正在填写 Word 文档...', '60%')
            fill_result = await table_filling_service.fill_word_template(
                source_files=source_files,
                template_file=template_file,
                user_instruction=request.user_instruction,
            )

        await update_progress('正在保存结果...', '90%')

        filled_doc = Document(
            filename=fill_result['output_filename'],
            original_filename=f'filled_{template_doc.original_filename}',
            file_type='xlsx' if template_doc.file_type == 'xlsx' else 'docx',
            doc_category='output',
            file_path=fill_result['output_path'],
            status='completed',
        )
        db.add(filled_doc)
        await db.commit()
        await db.refresh(filled_doc)

        usage_event = TemplateUsageEvent(
            template_id=request.template_file_id,
            template_name=template_doc.original_filename,
            source_file_count=len(request.source_file_ids),
            output_file_id=filled_doc.id,
            used_at=datetime.utcnow(),
        )
        db.add(usage_event)
        await db.commit()

        task.status = 'completed'
        task.filled_file_path = fill_result['output_path']
        task.result = {
            'progress': '100%',
            'current_step': '完成',
            'filled_doc_id': str(filled_doc.id),
            **fill_result.get('filled_data', {}),
        }
        task.completed_at = datetime.utcnow()
        await db.commit()

        return TableFillResponse(
            task_id=task.id,
            status='completed',
            filled_file_id=filled_doc.id,
            filled_file_url=f'/api/v1/table-fill/download/{filled_doc.id}',
            message='表格填写完成',
            result=fill_result.get('filled_data', {}),
        )
    except Exception as exc:
        task.status = 'failed'
        task.result = {
            'error': str(exc),
            'progress': '100%',
            'current_step': f'失败: {str(exc)}',
        }
        await db.commit()
        raise HTTPException(status_code=500, detail=str(exc))


@router.get('/stats/template-usage')
async def template_usage_stats(
    limit: int = 10,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    safe_limit = max(1, min(limit, 50))

    stmt = (
        select(
            TemplateUsageEvent.template_id,
            TemplateUsageEvent.template_name,
            func.count(TemplateUsageEvent.id).label('usage_count'),
        )
        .group_by(TemplateUsageEvent.template_id, TemplateUsageEvent.template_name)
        .order_by(func.count(TemplateUsageEvent.id).desc(), TemplateUsageEvent.template_name.asc())
        .limit(safe_limit)
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


@router.get('/download/{file_id}')
async def download_filled_table(
    file_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == file_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail='File not found')
    resolved_path = _resolve_document_path(doc.file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail='File not found on disk')

    return FileResponse(
        resolved_path,
        filename=doc.original_filename,
        media_type=_get_file_media_type(doc.file_type),
    )


@router.get('/output-files')
async def list_output_files(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document)
        .where(Document.doc_category == 'output')
        .offset(skip)
        .limit(limit)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.get('/download-file/{filename}')
async def download_filled_file(filename: str):
    file_path = _resolve_document_path(os.path.join('./uploads/output', filename))
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail='File not found')

    return FileResponse(
        file_path,
        filename=filename,
        media_type=_get_file_media_type(os.path.splitext(filename)[1].lstrip('.')),
    )


@router.get('/tasks', response_model=List[dict])
async def list_tasks(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    docs_result = await db.execute(select(Document.id, Document.original_filename))
    doc_map = {str(doc.id): doc.original_filename for doc in docs_result.all()}

    result = await db.execute(
        select(TableFillTask)
        .order_by(TableFillTask.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    tasks = result.scalars().all()

    task_list = []
    for task in tasks:
        template_name = doc_map.get(str(task.template_file_id), '未知模板')

        source_names = []
        if task.source_file_ids:
            for file_id in task.source_file_ids:
                source_names.append(doc_map.get(file_id, '未知文件'))

        progress = '0%'
        current_step = ''
        filled_doc_id = None
        if task.result and isinstance(task.result, dict):
            progress = task.result.get('progress', '0%')
            current_step = task.result.get('current_step', '')
            filled_doc_id = task.result.get('filled_doc_id')

        estimated_time = None
        if task.status == 'processing' and task.created_at and progress != '0%':
            try:
                elapsed = (datetime.utcnow() - task.created_at).total_seconds()
                progress_num = int(progress.replace('%', ''))
                if 0 < progress_num < 100:
                    estimated_seconds = (elapsed / progress_num) * (100 - progress_num)
                    if estimated_seconds < 60:
                        estimated_time = f'约 {int(estimated_seconds)} 秒'
                    elif estimated_seconds < 3600:
                        minutes = int(estimated_seconds // 60)
                        seconds = int(estimated_seconds % 60)
                        estimated_time = f'约 {minutes} 分 {seconds} 秒'
                    else:
                        hours = int(estimated_seconds // 3600)
                        minutes = int((estimated_seconds % 3600) // 60)
                        estimated_time = f'约 {hours} 小时 {minutes} 分'
            except Exception:
                estimated_time = None

        filled_file_url = f'/api/v1/table-fill/download/{filled_doc_id}' if filled_doc_id and filled_doc_id != 'None' else None

        task_list.append(
            {
                'id': str(task.id),
                'status': task.status,
                'source_files': task.source_file_ids or [],
                'source_names': source_names,
                'template_name': template_name,
                'filled_file_id': filled_doc_id if filled_file_url else None,
                'filled_file_url': filled_file_url,
                'progress': progress,
                'current_step': current_step,
                'estimated_time': estimated_time,
                'created_at': task.created_at.isoformat() if task.created_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                'error': task.result.get('error') if task.result and isinstance(task.result, dict) else None,
            }
        )

    return task_list


@router.get('/tasks/{task_id}')
async def get_task_status(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(TableFillTask).where(TableFillTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')

    return {
        'task_id': task.id,
        'status': task.status,
        'result': task.result,
        'created_at': task.created_at,
        'completed_at': task.completed_at,
    }
