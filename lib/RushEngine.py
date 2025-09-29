import functools
import json
from httpx import get
from pydantic import BaseModel
from exchange.aster.AsterExchangeAccountV1 import AsterExchangeAccountV1
from lib.ExchangeAccount import ExchangeAccount
from lib.RushTask import RushTask, RushTaskStatus
from exchange.aster.AsterAccountV1 import AsterAccountV1
import random
import asyncio
import config
import uuid
from lib.logger import get_logger
from lib.tools import now
import os
import datetime


logger = get_logger(__name__)

exchange_map = {
    "aster": AsterAccountV1,
}


class RushEngine(BaseModel):
    """
    交易引擎类
    """

    accounts: dict[str, ExchangeAccount] = {}
    running_tasks: dict[str, RushTask] = {}
    completed_tasks: list[RushTask] = []
    failed_tasks: list[RushTask] = []
    # account_id -> task_id -> task
    account_running_tasks: dict[str, dict[str, RushTask]] = {}

    max_concurrent_tasks: int = config.max_concurrent_tasks

    async def simulate_callback(self):
        """
        模拟回调函数
        """
        while True:
            for _, task in self.running_tasks.items():
                if len(task.open_orders) == 0:
                    continue
                target_order_id = random.choice(list(task.open_orders.keys()))
                target_order = task.open_orders[target_order_id]
                data = {
                    "e": "ORDER_TRADE_UPDATE",
                    "E": now(),
                    "T": now(),
                    "o": {"x": "FILLED", "X": "FILLED", "i": target_order.order_result["orderId"]},
                }
                self.callback(account_id=target_order.account_id, message=json.dumps(data))

            await asyncio.sleep(5)

    def callback(self, *, account_id: str, message: str):
        """
        账户回调函数
        """
        logger.info(f"账户 [{account_id}] 回调消息：{message}")
        if account_id in self.account_running_tasks:
            for _, task in self.account_running_tasks[account_id].items():
                data = json.loads(message)
                task.order_update_callback(message=data)

    def generate_available_account_symbols(self) -> dict[str, list[str]]:
        """
        生成交易对的可用账户列表

        Returns:
            dict[str, list[str]]: 交易对的可用账户列表 symbol -> account_id列表
        """
        result: dict[str, list[str]] = {}
        for symbol in config.symbols:
            result[symbol] = []
            for account_id, account in self.accounts.items():
                # 检查账户是否支持该交易对
                if symbol in account.symbols:
                    _account_running_tasks = self.account_running_tasks.get(account_id)
                    if _account_running_tasks is None:
                        result[symbol].append(account_id)
                    else:
                        # 该账户正在运行的任务中 是否存在相同symbol的任务
                        any_task_running = any(task.symbol == symbol for _, task in _account_running_tasks.items())
                        # 如果不存在 则该账户可以执行 该交易对的任务
                        if not any_task_running:
                            result[symbol].append(account_id)
            # 如果该交易对 没有足够的可用账户 则移除该交易对
            if len(result[symbol]) < 2:
                result.pop(symbol)

        return result

    def generate_next_task(self) -> RushTask | None:
        """
        生成下一个任务
        """
        available_account_symbols = self.generate_available_account_symbols()
        if len(available_account_symbols) == 0:
            return None
        picked_symbol = random.choice(list(available_account_symbols.keys()))
        available_account_ids = available_account_symbols[picked_symbol]
        if len(available_account_ids) < 2:
            return None
        first_account_id = random.choice(available_account_ids)
        available_account_ids.remove(first_account_id)
        second_account_id = random.choice(available_account_ids)
        if first_account_id == second_account_id:
            return None

        return RushTask(
            id=f"RT-{picked_symbol}-{uuid.uuid4().hex}",
            symbol=picked_symbol,
            first_account=self.accounts[first_account_id],
            second_account=self.accounts[second_account_id],
        )

    def remove_finished_tasks(self):
        """
        移除已完成的任务
        """
        remove_task_ids: list[str] = []
        for task_id, task in self.running_tasks.items():
            first_account_id = task.first_account.account.id
            second_account_id = task.second_account.account.id
            if task.status == RushTaskStatus.COMPLETED:
                remove_task_ids.append(task_id)
                self.completed_tasks.append(task)
                # 从账户运行任务中移除
                for account_id in [first_account_id, second_account_id]:
                    if account_id in self.account_running_tasks:
                        self.account_running_tasks[account_id].pop(task_id)
            elif task.status == RushTaskStatus.FAILED:
                remove_task_ids.append(task_id)
                self.failed_tasks.append(task)
                # 从账户运行任务中移除
                for account_id in [first_account_id, second_account_id]:
                    if account_id in self.account_running_tasks:
                        self.account_running_tasks[account_id].pop(task_id)
                # 终止程序，通知用户需要手动检查账号是否有未完成的订单
                logger.error(f"任务 {task_id} 失败，账户 {first_account_id} 和 {second_account_id} 可能有未完成的订单")
                raise ValueError(f"任务 {task_id} 失败，账户 {first_account_id} 和 {second_account_id} 可能有未完成的订单")

        # 移除已完成的任务
        for task_id in remove_task_ids:
            self.running_tasks.pop(task_id)

    async def task_runner(self, *, times=100):
        """
        任务运行器
        """
        while not self.check_stop() and len(self.completed_tasks) + len(self.failed_tasks) < times:
            # 1. 移除已完成的任务
            self.remove_finished_tasks()

            # 2. 如果还有任务且未达到最大并发，创建新任务
            while len(self.running_tasks) < self.max_concurrent_tasks:
                task = self.generate_next_task()
                if task is None:
                    break
                self.running_tasks[task.id] = task
                first_account_id = task.first_account.account.id
                second_account_id = task.second_account.account.id
                for account_id in [first_account_id, second_account_id]:
                    if account_id not in self.account_running_tasks:
                        self.account_running_tasks[account_id] = {}
                    self.account_running_tasks[account_id][task.id] = task
                # 启动任务加入间隔，避免同时启动所有任务
                await asyncio.sleep(1)
                # 启动任务
                asyncio.create_task(task.run())

            # 3. 如果完成的任务大于20条，保存一次
            # 不需要这里保存了，等一次引擎循环结束后自动保存
            # if len(self.completed_tasks) + len(self.failed_tasks) >= 20:
            #     self.save_tasks()

            # 4. 短暂休眠，避免空循环占用CPU
            await asyncio.sleep(config.RushEngineInterval)

        logger.info("安全退出，等待所有任务完成")
        # 标记所有运行中的任务为停止
        for task in self.running_tasks.values():
            task.stop = True
        while len(self.running_tasks) > 0:
            self.remove_finished_tasks()
            await asyncio.sleep(1)
            if self.check_error():
                logger.error("发现错误强制退出标示，跳出等待任务完成，直接开始清理工作")
                break

        # 5. 结束保存任务
        self.save_tasks()
        # 6. 清理账户订单，持仓
        await self.clear_all()
        # 7. 关闭所有账户连接
        for account in self.accounts.values():
            await account.close()

        if self.check_error():
            raise ValueError("发现错误强制退出标示，终止程序")

    async def clear_all(self):
        """
        清理所有任务
        """
        tasks = []
        for account in self.accounts.values():
            # 清仓挂单
            tasks.append(asyncio.create_task(account.cancel_all_open_orders()))
            # 清仓持仓
            tasks.append(asyncio.create_task(account.clear_all_positions()))

        # 等待所有任务完成
        await asyncio.gather(*tasks, return_exceptions=True)

    def check_error(self):
        """
        检查是否有错误强制退出标示
        """
        return os.path.exists("error")

    def check_stop(self) -> bool:
        """
        检查是否需要停止引擎
        """
        return os.path.exists("shutdown")

    async def start(self, *, times=100):
        """
        启动交易引擎
        """
        # 启动账户任务
        logger.info(f"Rush Engine 启动!")
        account_tasks: list[asyncio.Task] = []
        for account_dict in config.accounts:
            accountClass = exchange_map[account_dict["exchange"]]
            if account_dict.get("id") is None:
                account_dict["id"] = "A-" + uuid.uuid4().hex
            account = accountClass(**account_dict)
            if isinstance(account, AsterAccountV1):
                exchangeAccount = AsterExchangeAccountV1()
                self.accounts[account.id] = exchangeAccount
                account_tasks.append(asyncio.create_task(exchangeAccount.init(account=account, callback=functools.partial(self.callback, account_id=account.id))))

        logger.info(f"开始初始化 {len(self.accounts)} 个账户")
        # 等待账户初始化完成
        while any(not account.ready for account in self.accounts.values()):
            await asyncio.sleep(0.1)

        logger.info(f"账户初始化完成 共初始化 {len(self.accounts)} 个账户, 开始设置杠杆。")

        # 设置杠杆
        leverage_tasks = []
        for account in self.accounts.values():
            for symbol in config.symbols:
                leverage_tasks.append(asyncio.create_task(account.set_leverage(symbol=symbol, leverage=config.leverage)))

        # 等待所有杠杆设置完成
        await asyncio.gather(*leverage_tasks, return_exceptions=True)
        logger.info(f"杠杆设置完成 启动交易")

        # 启动任务运行器
        await self.task_runner(times=times)

    def save_tasks(self):
        """
        保存执行完成的RushTask
        """
        if config.simulate:
            logger.info("模拟模式，不保存任务")
            return
        file_name_map = {0: "completed_tasks", 1: "failed_tasks"}
        exclude = {
            "first_account",
            "second_account",
        }
        folder = os.path.join("data", "tasks")
        if not os.path.exists(folder):
            os.makedirs(folder)
        for index, task_list in enumerate([self.completed_tasks, self.failed_tasks]):
            if len(task_list) == 0:
                continue
            save_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            file_name = file_name_map[index] + "_" + save_time + ".json"
            with open(os.path.join(folder, file_name), "w") as f:
                json.dump([task.model_dump(exclude=exclude) for task in task_list], f, indent=2)
                logger.info(f"已保存 {len(task_list)} 条 {file_name_map[index]}")
            task_list.clear()
