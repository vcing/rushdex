import logging
import logging.handlers
import os
import sys
import queue
import threading
import multiprocessing
from datetime import datetime
from typing import Optional, Dict, Any, Union, List

# 多进程日志配置
def setup_multiprocess_logging(log_file: Optional[str] = None, level: str = 'INFO') -> tuple[logging.Logger, logging.handlers.QueueListener, multiprocessing.Queue]:
    """
    设置多进程日志记录
    :param log_file: 日志文件路径，为None则只输出到控制台
    :param level: 日志级别
    :return: (logger, queue_listener, log_queue) 元组
    """
    # 创建一个多进程队列
    log_queue = multiprocessing.Queue()

    # 创建一个日志记录器
    logger = logging.getLogger('multiprocess')
    logger.setLevel(getattr(logging, level.upper()))
    logger.propagate = False

    # 移除已存在的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 添加队列处理器
    queue_handler = logging.handlers.QueueHandler(log_queue)
    logger.addHandler(queue_handler)

    # 创建处理器列表
    handlers: List[logging.Handler] = []

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    handlers.append(console_handler)

    # 文件处理器
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        handlers.append(file_handler)

    # 创建队列监听器
    queue_listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)

    return logger, queue_listener, log_queue

# 结束多进程日志
def shutdown_multiprocess_logging(queue_listener: logging.handlers.QueueListener) -> None:
    """
    关闭多进程日志监听器
    :param queue_listener: 队列监听器实例
    """
    queue_listener.stop()
class Logger:
    def __init__(self, name: str = 'app', level: str = 'INFO', log_file: Optional[str] = None):
        """
        初始化日志记录器
        :param name: 日志记录器名称
        :param level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        :param log_file: 日志文件路径，为None则只输出到控制台
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.logger.propagate = False  # 避免日志冗余

        # 移除已存在的处理器
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # 定义日志格式
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # 文件处理器
        if log_file:
            # 确保目录存在
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def set_level(self, level: str) -> None:
        """
        设置日志级别
        :param level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.logger.setLevel(getattr(logging, level.upper()))

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        记录调试信息
        :param message: 日志信息
        :param args: 格式化字符串参数
        :param kwargs: 额外参数
        """
        self.logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        记录一般信息
        :param message: 日志信息
        :param args: 格式化字符串参数
        :param kwargs: 额外参数
        """
        self.logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        记录警告信息
        :param message: 日志信息
        :param args: 格式化字符串参数
        :param kwargs: 额外参数
        """
        self.logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        记录错误信息
        :param message: 日志信息
        :param args: 格式化字符串参数
        :param kwargs: 额外参数
        """
        self.logger.error(message, *args, **kwargs)

    def critical(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        记录严重错误信息
        :param message: 日志信息
        :param args: 格式化字符串参数
        :param kwargs: 额外参数
        """
        self.logger.critical(message, *args, **kwargs)


# 创建一个默认的日志记录器实例
_default_logger = Logger()

def get_logger(name: Optional[str] = None) -> Logger:
    """
    获取日志记录器实例
    :param name: 日志记录器名称，为None则返回默认实例
    :return: 日志记录器实例
    """
    if name is None:
        return _default_logger
    return Logger(name)

# 导出常用方法，方便直接使用

def debug(message: str, *args: Any, **kwargs: Any) -> None:
    _default_logger.debug(message, *args, **kwargs)

def info(message: str, *args: Any, **kwargs: Any) -> None:
    _default_logger.info(message, *args, **kwargs)

def warning(message: str, *args: Any, **kwargs: Any) -> None:
    _default_logger.warning(message, *args, **kwargs)

def error(message: str, *args: Any, **kwargs: Any) -> None:
    _default_logger.error(message, *args, **kwargs)

def critical(message: str, *args: Any, **kwargs: Any) -> None:
    _default_logger.critical(message, *args, **kwargs)

def set_level(level: str) -> None:
    _default_logger.set_level(level)