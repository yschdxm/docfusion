import asyncio
import json
import logging
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, ExtractionTask
from app.models.user_agently_token import UserAgentlyToken
from app.services import file_storage

logger = logging.getLogger(__name__)
SUPPORTED_IMPORT_EXTENSIONS = {"docx", "xlsx", "md", "txt"}


class AgentlyMailService:
    """Tencent Agent Mail agently-cli 适配层。

    已确定命令：
    - agently-cli +me

    邮件列表/详情/发送/附件下载命令通过 .env 模板配置，以兼容 skill 子命令变化：
    - AGENTLY_MAIL_LIST_COMMAND: $limit
    - AGENTLY_MAIL_DETAIL_COMMAND: $message_id
    - AGENTLY_MAIL_SEND_COMMAND: $to $subject $body $attachments_json
    - AGENTLY_MAIL_ATTACHMENT_COMMAND: $message_id $attachment_id $output_dir
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _resolve_cli_bin(self) -> str:
        configured = self.settings.AGENTLY_CLI_BIN or "agently-cli"

        if shutil.which(configured):
            return configured

        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path)

        if configured == "agently-cli":
            for candidate in (
                Path.home() / "AppData" / "Roaming" / "npm" / "agently-cli.cmd",
                Path.home() / "AppData" / "Roaming" / "npm" / "agently-cli",
            ):
                if candidate.exists():
                    return str(candidate)

        return configured

    def _command_args(self, command: str | list[str]) -> list[str]:
        if isinstance(command, list):
            return command
        return shlex.split(command, posix=os.name != "nt")

    async def _run_command(self, command: str | list[str], timeout: int | None = None, cwd: str | Path | None = None, user_token: str | None = None) -> str:
        """执行 agently-cli 命令。

        Windows + uvicorn/conda 环境下，asyncio.create_subprocess_exec 可能因事件循环策略
        抛出 NotImplementedError，因此这里使用 subprocess.run 并放到线程池中执行。

        Args:
            user_token: 用户专属的 OAuth token，传入后会设置 AGENTLY_TOKEN 环境变量
        """
        timeout = timeout or self.settings.AGENTLY_MAIL_TIMEOUT_SECONDS
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        env.setdefault("PAGER", "cat")
        env.setdefault("GIT_PAGER", "cat")
        env.setdefault("LESS", "-F -X")

        # 如果提供了用户 token，设置环境变量（实现用户隔离）
        if user_token:
            env["AGENTLY_ACCESS_TOKEN"] = user_token

        def run() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                self._command_args(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=str(cwd) if cwd else None,
                timeout=timeout,
                shell=False,
            )

        try:
            proc = await asyncio.to_thread(run)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail="未找到 agently-cli，请先安装并完成 OAuth 授权；如已安装，请在 .env 中将 AGENTLY_CLI_BIN 配置为 agently-cli.cmd 的完整路径") from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="agently-cli 执行超时") from exc

        out = proc.stdout.decode("utf-8", "replace").strip()
        err = proc.stderr.decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            raise HTTPException(status_code=502, detail=err or out or "agently-cli 执行失败")
        return out or err

    @staticmethod
    def _json_or_text(output: str) -> Any:
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"raw": output}

    @staticmethod
    def _unwrap_envelope(data: Any) -> Any:
        """兼容 agently-cli 常见 JSON envelope。

        部分命令会返回：
        - {"data": {"messages": [...]}}
        - {"result": {"items": [...]}}
        - {"ok": true, "data": ...}
        前端需要稳定拿到业务数据，因此这里向下解包一层。
        """
        if not isinstance(data, dict):
            return data

        for key in ("data", "result", "payload"):
            value = data.get(key)
            if isinstance(value, (dict, list)):
                return value

        return data

    @staticmethod
    def _extract_messages(data: Any) -> list[Any]:
        """从不同返回结构中提取邮件列表。"""
        if isinstance(data, list):
            return data

        if not isinstance(data, dict):
            return []

        for key in ("messages", "items", "list", "records", "mails", "emails"):
            value = data.get(key)
            if isinstance(value, list):
                return value

        for key in ("data", "result", "payload"):
            value = data.get(key)
            nested = AgentlyMailService._extract_messages(value)
            if nested:
                return nested

        return []

    def _render(self, template: str, **kwargs: Any) -> str:
        if not template.strip():
            raise HTTPException(
                status_code=501,
                detail="该邮件操作尚未配置 agently-cli 命令模板，请在 .env 中配置对应 AGENTLY_MAIL_*_COMMAND",
            )
        safe: dict[str, str] = {}
        for key, value in kwargs.items():
            raw = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
            safe[key] = shlex.quote(raw)
        return Template(template).safe_substitute(**safe)

    async def me(self, user_token: str | None = None) -> dict[str, Any]:
        output = await self._run_command([self._resolve_cli_bin(), "+me"], timeout=30, user_token=user_token)
        parsed = self._json_or_text(output)
        raw = parsed.get("raw") if isinstance(parsed, dict) else output
        email = None

        if isinstance(parsed, dict):
            # 直接在顶层查找
            email = parsed.get("email") or parsed.get("mail") or parsed.get("address")

            # 在 data 中查找
            if not email:
                data = parsed.get("data", {})
                if isinstance(data, dict):
                    email = data.get("email") or data.get("mail") or data.get("address")

                    # 在 aliases 中查找
                    if not email:
                        aliases = data.get("aliases", [])
                        if isinstance(aliases, list) and aliases:
                            for alias in aliases:
                                if isinstance(alias, dict) and alias.get("is_primary"):
                                    email = alias.get("email")
                                    break
                            if not email and isinstance(aliases[0], dict):
                                email = aliases[0].get("email")

        if not email and isinstance(raw, str):
            email = raw.splitlines()[-1].strip()

        return {"authorized": True, "email": email or "unknown", "raw": parsed}

    async def list_messages(self, limit: int = 20, user_token: str | None = None) -> dict[str, Any]:
        raw = self._json_or_text(await self._run_command([
            self._resolve_cli_bin(),
            "message",
            "+list",
            "--dir",
            "inbox",
            "--limit",
            str(limit),
        ], user_token=user_token))
        data = self._unwrap_envelope(raw)
        messages = self._extract_messages(raw)

        response: dict[str, Any] = {
            "messages": messages,
            "raw": raw,
        }

        if isinstance(data, dict):
            for key in ("next_cursor", "nextCursor", "cursor", "has_more", "hasMore", "total"):
                if key in data:
                    response[key] = data[key]

        return response

    async def get_message(self, message_id: str, user_token: str | None = None) -> dict[str, Any]:
        raw = self._json_or_text(await self._run_command([
            self._resolve_cli_bin(),
            "message",
            "+read",
            "--id",
            message_id,
        ], user_token=user_token))
        data = self._unwrap_envelope(raw)
        if isinstance(data, dict):
            return {**data, "raw": raw}
        return {"raw": raw}

    def _send_command_args(self, to: str, subject: str, body: str, attachments: list[str] | None = None) -> list[str]:
        command = [
            self._resolve_cli_bin(),
            "message",
            "+send",
            "--to",
            to,
            "--subject",
            subject,
            "--body",
            body,
        ]
        if attachments:
            for attachment in attachments:
                command.extend(["--attachment", attachment])
        return command

    async def send_message(self, to: str, subject: str, body: str, attachments: list[str] | None = None, user_token: str | None = None) -> dict[str, Any]:
        data = self._json_or_text(await self._run_command(self._send_command_args(to, subject, body, attachments), user_token=user_token))
        return data if isinstance(data, dict) else {"raw": data}

    async def confirm_send_message(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        confirmation_token: str,
        attachments: list[str] | None = None,
        user_token: str | None = None,
    ) -> dict[str, Any]:
        command = self._send_command_args(to, subject, body, attachments)
        command.extend(["--confirmation-token", confirmation_token])
        data = self._json_or_text(await self._run_command(command, user_token=user_token))
        return data if isinstance(data, dict) else {"raw": data}

    async def download_attachment(self, message_id: str, attachment_id: str, user_token: str | None = None) -> list[Path]:
        upload_root = Path(self.settings.UPLOAD_DIR)
        output_rel = Path("mail_attachments") / uuid4().hex
        output_dir = upload_root / output_rel
        output_dir.mkdir(parents=True, exist_ok=True)

        await self._run_command(
            [
                self._resolve_cli_bin(),
                "attachment",
                "+download",
                "--msg",
                message_id,
                "--att",
                attachment_id,
                "--output",
                output_rel.as_posix(),
            ],
            cwd=upload_root,
            user_token=user_token,
        )
        return [p for p in output_dir.rglob("*") if p.is_file()]

    async def import_attachment(self, *, db: AsyncSession, user_id: UUID, message_id: str, attachment_id: str, doc_category: str = "source", user_token: str | None = None) -> list[dict[str, Any]]:
        files = await self.download_attachment(message_id, attachment_id, user_token=user_token)
        imported: list[Document] = []
        Path(self.settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

        for source_path in files:
            ext = source_path.suffix.lower().lstrip(".")
            if ext not in SUPPORTED_IMPORT_EXTENSIONS:
                logger.info("skip unsupported mail attachment: %s", source_path)
                continue

            # 预生成文档 ID 作为 root_document_id，文件按版本化布局存储
            doc_id = uuid4()
            target_path = file_storage.version_path(user_id, doc_category, doc_id, 1, source_path.name)
            shutil.copyfile(source_path, target_path)
            size = target_path.stat().st_size

            doc = Document(
                id=doc_id,
                user_id=user_id,
                filename=target_path.name,
                original_filename=source_path.name,
                file_type=ext,
                doc_category=doc_category,
                file_size=size,
                file_path=str(target_path),
                status="uploaded",
                root_document_id=doc_id,
                version=1,
                origin_type="mail_import",
                sha256=file_storage.sha256_file(target_path),
                metadata_info={"source": "agent_mail", "message_id": message_id, "attachment_id": attachment_id},
            )
            db.add(doc)
            await db.flush()

            if doc_category == "source":
                db.add(ExtractionTask(
                    task_type="entity_extraction",
                    status="queued",
                    user_id=user_id,
                    input_files=[str(doc.id)],
                    config={"entity_types": "auto", "source": "agent_mail"},
                    result={"progress": "0%", "current_step": "等待处理...", "total_files": 1, "processed_files": 0},
                ))
            imported.append(doc)

        await db.commit()
        for doc in imported:
            await db.refresh(doc)

        return [{
            "id": str(doc.id),
            "filename": doc.filename,
            "original_filename": doc.original_filename,
            "file_type": doc.file_type,
            "doc_category": doc.doc_category,
            "file_size": doc.file_size,
            "status": doc.status,
            "metadata_info": doc.metadata_info or {},
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        } for doc in imported]

    # ==================== OAuth Token 管理 ====================

    async def get_user_token(self, db: AsyncSession, user_id: UUID) -> str | None:
        """获取用户的 Agently token"""
        result = await db.execute(
            select(UserAgentlyToken).where(UserAgentlyToken.user_id == user_id)
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            return None

        # 检查 token 是否过期
        if token_record.expires_at and token_record.expires_at < datetime.utcnow():
            # 尝试刷新 token
            if token_record.refresh_token:
                new_token = await self._refresh_token(token_record.refresh_token)
                if new_token:
                    await self.save_user_token(
                        db=db,
                        user_id=user_id,
                        access_token=new_token["access_token"],
                        refresh_token=new_token.get("refresh_token", token_record.refresh_token),
                        expires_in=new_token.get("expires_in"),
                        email=token_record.email,
                    )
                    return new_token["access_token"]
            return None

        return token_record.access_token

    async def save_user_token(
        self,
        db: AsyncSession,
        user_id: UUID,
        access_token: str,
        refresh_token: str | None = None,
        expires_in: int | None = None,
        email: str | None = None,
    ) -> UserAgentlyToken:
        """保存用户的 Agently token"""
        result = await db.execute(
            select(UserAgentlyToken).where(UserAgentlyToken.user_id == user_id)
        )
        token_record = result.scalar_one_or_none()

        expires_at = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        if token_record:
            # 更新现有记录
            token_record.access_token = access_token
            if refresh_token:
                token_record.refresh_token = refresh_token
            if expires_at:
                token_record.expires_at = expires_at
            if email:
                token_record.email = email
            token_record.updated_at = datetime.utcnow()
        else:
            # 创建新记录
            token_record = UserAgentlyToken(
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                email=email,
            )
            db.add(token_record)

        await db.commit()
        await db.refresh(token_record)
        return token_record

    async def delete_user_token(self, db: AsyncSession, user_id: UUID) -> bool:
        """删除用户的 Agently token"""
        result = await db.execute(
            select(UserAgentlyToken).where(UserAgentlyToken.user_id == user_id)
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            return False

        await db.delete(token_record)
        await db.commit()
        return True

    async def get_user_auth_status(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        """获取用户的授权状态"""
        token = await self.get_user_token(db, user_id)
        if not token:
            logger.info(f"[AUTH_STATUS] No token for user {user_id}")
            return {"authorized": False, "email": None}

        try:
            # 尝试获取用户信息来验证 token 有效性
            info = await self.me(user_token=token)
            logger.info(f"[AUTH_STATUS] User {user_id} info: {info}")
            return {
                "authorized": True,
                "email": info.get("email"),
            }
        except Exception as e:
            logger.error(f"[AUTH_STATUS] Failed to get user info: {e}", exc_info=True)
            return {"authorized": False, "email": None}

    async def _refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        """刷新 token：调用 agently OAuth token 端点（grant_type=refresh_token）。

        失败（网络错误、refresh_token 失效等）返回 None，调用方会要求用户重新授权。
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://auth.agent.qq.com/oauth/token",
                    json={"grant_type": "refresh_token", "refresh_token": refresh_token},
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "agently-cli/1.0.9",
                    },
                )
                if response.status_code != 200:
                    logger.warning(f"[TOKEN_REFRESH] HTTP {response.status_code}: {response.text[:200]}")
                    return None

                data = response.json()
                access_token = data.get("access_token")
                if not access_token:
                    logger.warning(f"[TOKEN_REFRESH] no access_token in response: {str(data)[:200]}")
                    return None

                logger.info("[TOKEN_REFRESH] token refreshed successfully")
                return {
                    "access_token": access_token,
                    "refresh_token": data.get("refresh_token"),
                    "expires_in": data.get("expires_in"),
                }
        except Exception as e:
            logger.error(f"[TOKEN_REFRESH] refresh failed: {e}")
            return None


agently_mail_service = AgentlyMailService()
