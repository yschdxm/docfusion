"""一次性工作区重置脚本：清空所有文档/任务/对话数据与 uploads 目录，仅保留 users 和 system_config。

用法：
    cd backend
    python scripts/reset_workspace.py        # 交互确认后执行
    python scripts/reset_workspace.py --yes  # 跳过确认
"""

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.postgres import engine  # noqa: E402

TABLES = [
    "template_usage_events",
    "document_extractions",
    "extraction_tasks",
    "table_fill_tasks",
    "messages",
    "conversations",
    "documents",
]

KEEP_TABLES = ["users", "system_config", "user_agently_tokens"]


async def reset_database() -> None:
    async with engine.begin() as conn:
        for table in TABLES:
            await conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            print(f"  已清空表: {table}")


def reset_uploads() -> None:
    upload_dir = Path(get_settings().UPLOAD_DIR)
    if not upload_dir.exists():
        print(f"  uploads 目录不存在，跳过: {upload_dir}")
        return
    removed = 0
    for child in upload_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    print(f"  已清空 uploads 目录: {upload_dir}（删除 {removed} 项）")


async def main() -> None:
    parser = argparse.ArgumentParser(description="重置工作区数据（保留账号）")
    parser.add_argument("--yes", action="store_true", help="跳过确认直接执行")
    args = parser.parse_args()

    print("将执行以下破坏性操作：")
    print(f"  - TRUNCATE 表: {', '.join(TABLES)}")
    print(f"  - 清空 uploads 目录: {Path(get_settings().UPLOAD_DIR).resolve()}")
    print(f"  - 保留表: {', '.join(KEEP_TABLES)}")

    if not args.yes:
        confirm = input("\n确认执行？输入 yes 继续: ").strip()
        if confirm != "yes":
            print("已取消")
            return

    print("\n清空数据库...")
    await reset_database()
    print("清空 uploads 目录...")
    reset_uploads()
    print("\n重置完成。账号数据未受影响。")


if __name__ == "__main__":
    asyncio.run(main())
