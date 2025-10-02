import json
import config
import asyncio
import signal
import os
import httpx
from lib.logger import get_logger
from lib.RushEngine import RushEngine

logger = get_logger(__name__)

def check_bark():
    if not config.bark_url:
        logger.error("bark_url 未配置, 无法发送通知")
        return False
    if os.path.exists("bark"):
        logger.info("bark 通知已发送, 无需重复发送")
        return False
    return True

async def send_bark_async():
    if not check_bark():
        return
    url = config.bark_url
    message = "Rushdex 异常退出，请检查。"
    if "这里改成你自己的推送内容" in url:
        url = url.replace("这里改成你自己的推送内容", message)
    elif url.endswith("/"):
        url += message
    else:
        url += f"/{message}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code != 200:
            logger.error(f"发送bark通知失败, 状态码: {response.status_code}, 响应内容: {response.text}")
        else:
            logger.info(f"发送bark通知成功, 响应内容: {response.text}")
            with open("bark", "w") as f:
                f.write("bark")

def global_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, any]) -> None:
    # 1. 先打印完整的异常上下文（asyncio 提供的所有信息），避免遗漏关键信息
    logger.error(
        "全局异常处理器捕获到事件循环错误:" + json.dumps(context, default=str),
        extra={"asyncio_context": context},  # 附加完整上下文到日志
        exc_info=context.get("exception")  # 强制日志记录异常堆栈
    )

    # 2. 异步执行 send_bark，避免阻塞事件循环（同步操作会导致循环卡死）
    try:
        # 使用事件循环创建任务，而非直接 await（处理器是同步函数，不能 await）
        asyncio.create_task(send_bark_async())
    except Exception as e:
        logger.error(f"创建 send_bark 任务失败: {str(e)}", exc_info=True)

    # 3. 标记错误状态（文件写入建议加异常捕获，避免处理器自身抛错）
    try:
        with open("error", "w") as f:
            f.write(f"error: {str(context.get('exception', '未知异常'))}")  # 写入具体异常
    except Exception as e:
        logger.error(f"写入 error 文件失败: {str(e)}", exc_info=True)

def check_stop() -> bool:
    """
    检查是否需要停止引擎
    """
    return os.path.exists("shutdown")

async def main():

    # 信号处理函数：仅设置标志，不做任何中断操作
    def handle_signal(signum, frame):
        signal_name = signal.Signals(signum).name
        logger.info(f"收到 {signal_name}，将在当前任务完成后退出")
        # 软终止标示
        with open("shutdown", "w") as f:
            f.write("shutdown")
        # os.environ["RUSH_ENGINE_SHUTDOWN"] = "1"

    # 关键：覆盖所有终止信号的默认处理，避免Python触发KeyboardInterrupt
    signal.signal(signal.SIGINT, handle_signal)  # 处理Ctrl+C
    signal.signal(signal.SIGTERM, handle_signal)  # 处理kill命令

    # 启动前清除shutdown文件
    if os.path.exists("shutdown"):
        os.remove("shutdown")
    if os.path.exists("error"):
        os.remove("error")
    if os.path.exists("bark"):
        os.remove("bark")

    loop = asyncio.get_running_loop()
    # 设置全局异常处理器
    loop.set_exception_handler(global_exception_handler)
    while not check_stop():
        # 创建引擎
        rush_engine = RushEngine()
        if config.simulate:
            logger.info("模拟模式，开启模拟回调")
            asyncio.create_task(rush_engine.simulate_callback())
        # 每一轮默认执行100次任务，执行完成后会自动清理账户持仓和订单，防止一些细节问题。
        # 一轮任务执行时间预估为 100 / 并发数量 * 每个任务的平均执行时间(主要是等待持仓时间)
        await rush_engine.start(times=100)
    
    logger.info("引擎已停止")


if __name__ == "__main__":
    # 主程序不捕获任何异常（确保引擎能完整执行）
    asyncio.run(main())
