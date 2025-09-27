from loguru import logger
from loguru._logger import Logger
import os

folder = os.path.join("data", "logs")

if not os.path.exists(folder):
    os.makedirs(folder)

logger.add(
    os.path.join(folder, "file_{time}.log"), 
    rotation="00:00", 
    retention="30 days", 
    compression="zip", 
    encoding="utf-8"
)  # 每天午夜滚动  # 保留30天  # 压缩历史日志


def get_logger(module: str) -> Logger:
    return logger.bind(module=module)
