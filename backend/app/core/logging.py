import logging
import logging.config
import sys

from app.core.config import get_settings


class ColorFormatter(logging.Formatter):
    """带颜色的日志格式化器，仅在 stderr 是终端时生效。"""

    COLORS = {
        "DEBUG":    "\033[36m",   # 青色
        "INFO":     "\033[32m",   # 绿色
        "WARNING":  "\033[33m",   # 黄色
        "ERROR":    "\033[31m",   # 红色
        "CRITICAL": "\033[1;31m", # 加粗红色
    }
    RESET = "\033[0m"

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.use_color = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    def format(self, record):
        if self.use_color:
            color = self.COLORS.get(record.levelname, "")
            record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        else:
            record.levelname = f"{record.levelname:<8}"
        return super().format(record)


def setup_logging():
    """初始化集中式日志配置。

    支持的环境变量：
        LOG_LEVEL           - 全局默认级别 (默认 INFO)
        LOG_LEVEL_DB        - 数据库层 (postgres, mongodb, neo4j) (默认 WARNING)
        LOG_LEVEL_SERVICE   - services/ 层级 (默认 INFO)
        LOG_LEVEL_API       - api/v1/endpoints/ 层级 (默认 INFO)
        LOG_LEVEL_LLM       - llm_service 单独控制 (默认 INFO)
        LOG_LEVEL_KG        - knowledge_graph_service 单独控制 (默认 INFO)
        LOG_LEVEL_RAG       - rag_service 单独控制 (默认 INFO)
        LOG_LEVEL_UVICORN   - uvicorn (默认 WARNING)
        LOG_LEVEL_SQLALCHEMY - sqlalchemy (默认 WARNING)
        LOG_LEVEL_NEO4J_DRIVER - neo4j 驱动 (默认 WARNING)
        LOG_LEVEL_MOTOR     - motor/pymongo (默认 WARNING)
        LOG_LEVEL_REDIS     - redis (默认 WARNING)
        LOG_LEVEL_CELERY    - celery (默认 WARNING)
    """
    settings = get_settings()
    s = settings

    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,

        "formatters": {
            "color": {
                "()": ColorFormatter,
                "format": log_format,
                "datefmt": date_format,
            },
        },

        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "color",
                "stream": "ext://sys.stderr",
            },
        },

        "loggers": {
            # ── 应用日志 ──
            "app": {
                "level": s.LOG_LEVEL,
                "handlers": ["console"],
                "propagate": False,
            },
            "app.db": {
                "level": s.LOG_LEVEL_DB,
                "handlers": ["console"],
                "propagate": False,
            },
            "app.services": {
                "level": s.LOG_LEVEL_SERVICE,
                "handlers": ["console"],
                "propagate": False,
            },
            # 高频服务模块单独控制
            "app.services.llm_service": {
                "level": s.LOG_LEVEL_LLM,
                "handlers": ["console"],
                "propagate": False,
            },
            "app.services.knowledge_graph_service": {
                "level": s.LOG_LEVEL_KG,
                "handlers": ["console"],
                "propagate": False,
            },
            "app.services.rag_service": {
                "level": s.LOG_LEVEL_RAG,
                "handlers": ["console"],
                "propagate": False,
            },
            "app.api": {
                "level": s.LOG_LEVEL_API,
                "handlers": ["console"],
                "propagate": False,
            },

            # ── 第三方库日志 ──
            "uvicorn":         {"level": s.LOG_LEVEL_UVICORN, "handlers": ["console"], "propagate": False},
            "uvicorn.error":   {"level": s.LOG_LEVEL_UVICORN, "handlers": ["console"], "propagate": False},
            "uvicorn.access":  {"level": s.LOG_LEVEL_UVICORN, "handlers": ["console"], "propagate": False},
            "fastapi":         {"level": s.LOG_LEVEL_UVICORN, "handlers": ["console"], "propagate": False},
            "sqlalchemy":      {"level": s.LOG_LEVEL_SQLALCHEMY, "handlers": ["console"], "propagate": False},
            "neo4j":           {"level": s.LOG_LEVEL_NEO4J_DRIVER, "handlers": ["console"], "propagate": False},
            "pymongo":         {"level": s.LOG_LEVEL_MOTOR,   "handlers": ["console"], "propagate": False},
            "motor":           {"level": s.LOG_LEVEL_MOTOR,   "handlers": ["console"], "propagate": False},
            "redis":           {"level": s.LOG_LEVEL_REDIS,   "handlers": ["console"], "propagate": False},
            "celery":          {"level": s.LOG_LEVEL_CELERY,  "handlers": ["console"], "propagate": False},
        },

        "root": {
            "level": s.LOG_LEVEL,
            "handlers": ["console"],
        },
    })
