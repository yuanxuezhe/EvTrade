"""
file_logging — root logger 双写 console + 文件

server-interaction-logging REQ-LOG-006 增量:
- console handler 保留 (uvicorn 容器 stderr 可看)
- 新增 TimedRotatingFileHandler, 每天一个文件 logs/server-YYYYMMDD.log
- 保留 7 天 (backupCount=6, 含今天共 7 个)
- format: "[%(asctime)s][%(levelname)s][%(name)s] %(message)s"
  (比 console 多 [%(name)s] logger 名, 便于 grep 定位)

Python 3.6 兼容:
- TimedRotatingFileHandler 是 stdlib, 无需新依赖
- 不依赖 zoneinfo / relativedelta

被 main.py 在 logging.basicConfig 之后调用一次:
    from server.utils.file_logging import setup_file_logging
    setup_file_logging(log_dir=os.path.join(os.path.dirname(__file__), "..", "logs"))
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOG_FORMAT_FILE = "[%(asctime)s][%(levelname)s][%(name)s] %(message)s"
LOG_FORMAT_CONSOLE = "[%(asctime)s][%(levelname)s] %(message)s"
DEFAULT_LOG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "logs"
)
DEFAULT_PREFIX = "server"
BACKUP_DAYS = 6  # 含今天共 7 天


def setup_file_logging(
    log_dir: str = None,
    prefix: str = DEFAULT_PREFIX,
    level: int = logging.INFO,
    backup_days: int = BACKUP_DAYS,
) -> str:
    """
    给 root logger 加 TimedRotatingFileHandler, 保留 console handler 不动.

    Args:
        log_dir: 日志目录; None 则默认 server/logs/
        prefix: 文件名前缀 (server-YYYYMMDD.log)
        level: 文件日志级别 (默认 INFO)
        backup_days: 保留天数 (默认 7 天)

    Returns:
        实际日志目录的绝对路径 (供调试 / 测试校验)
    """
    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR
    log_dir = os.path.abspath(log_dir)

    # 创建目录 (幂等)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        # 目录创建失败 (权限/只读文件系统) 时不阻塞启动, 仅 console 输出
        logging.warning("[file_logging] cannot create log dir %s: %s", log_dir, e)
        return log_dir

    root = logging.getLogger()

    # 幂等: 同一个文件 handler 别重复挂
    for h in root.handlers:
        if isinstance(h, TimedRotatingFileHandler) and getattr(h, "_evtrade_file_log", False):
            return log_dir

    file_name = os.path.join(log_dir, f"{prefix}.log")
    fh = TimedRotatingFileHandler(
        filename=file_name,
        when="midnight",
        interval=1,
        backupCount=backup_days,
        encoding="utf-8",
        utc=False,  # 本地时区, 跟 console 一致
    )
    # suffix: 默认 server.log.YYYY-MM-DD, 改名 server-YYYY-MM-DD.log
    fh.suffix = "%Y-%m-%d"
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(LOG_FORMAT_FILE))
    fh._evtrade_file_log = True  # 自定义标记, 防重复挂
    root.addHandler(fh)

    logging.info(
        "[file_logging] file handler enabled: dir=%s file=%s backup=%ddays",
        log_dir, file_name, backup_days + 1,
    )
    return log_dir


__all__ = [
    "setup_file_logging",
    "LOG_FORMAT_FILE",
    "LOG_FORMAT_CONSOLE",
    "DEFAULT_LOG_DIR",
]