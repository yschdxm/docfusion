import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from fastapi import HTTPException

from app.core.config import get_settings


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _validate_config(self) -> None:
        required = {
            "SMTP_SERVER": self.settings.SMTP_SERVER,
            "SMTP_PORT": str(self.settings.SMTP_PORT or ""),
            "SMTP_USER": self.settings.SMTP_USER,
            "SMTP_PASSWORD": self.settings.SMTP_PASSWORD,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise HTTPException(
                status_code=500,
                detail=f"邮件服务未正确配置，缺少：{', '.join(missing)}",
            )

    def send_document_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        attachment_path: str,
        attachment_name: str,
    ) -> None:
        self._validate_config()

        file_path = Path(attachment_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="待发送附件不存在")

        message = EmailMessage()
        message["From"] = self.settings.SMTP_USER
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body or "")

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"

        with file_path.open("rb") as f:
            message.add_attachment(
                f.read(),
                maintype=maintype,
                subtype=subtype,
                filename=attachment_name,
            )

        with smtplib.SMTP(self.settings.SMTP_SERVER, self.settings.SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
            server.send_message(message)


email_service = EmailService()