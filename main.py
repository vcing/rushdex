import config
import asyncio
import signal
import os
from lib.logger import get_logger
from lib.RushEngine import RushEngine

logger = get_logger(__name__)


def global_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, any]) -> None:
    # 获取异常对象
    exception: Exception = context.get("exception")

    if exception:
        logger.error(f"捕获到异常, 终止程序: {exception}")
        loop.stop()


async def main():
    # 创建引擎
    rush_engine = RushEngine()
    if config.simulate:
        logger.info("模拟模式，开启模拟回调")
        asyncio.create_task(rush_engine.simulate_callback())

    # 信号处理函数：仅设置标志，不做任何中断操作
    def handle_signal(signum, frame):
        signal_name = signal.Signals(signum).name
        logger.info(f"收到 {signal_name}，将在当前任务完成后退出")
        with open("shutdown", "w") as f:
            f.write("shutdown")
        # os.environ["RUSH_ENGINE_SHUTDOWN"] = "1"

    # 关键：覆盖所有终止信号的默认处理，避免Python触发KeyboardInterrupt
    signal.signal(signal.SIGINT, handle_signal)  # 处理Ctrl+C
    signal.signal(signal.SIGTERM, handle_signal)  # 处理kill命令

    # 启动前清除shutdown文件
    if os.path.exists("shutdown"):
        os.remove("shutdown")

    loop = asyncio.get_running_loop()
    # 设置全局异常处理器
    loop.set_exception_handler(global_exception_handler)
    await rush_engine.start()


if __name__ == "__main__":
    # 主程序不捕获任何异常（确保引擎能完整执行）
    asyncio.run(main())
