import asyncio
from enum import Enum
import uuid
from pydantic import BaseModel
from lib.ExchangeAccount import ExchangeAccount
from lib.tools import now
from model.PositionPrice import PositionPrice
from model.FilledOrder import FilledOrder
from model.Order import Order, OrderHoldType
from model.CanceledOrder import CanceledOrder
from model.OrderParams import OrderParams, OrderSide, OrderTimeInForce, OrderType
import random
from lib.logger import get_logger

logger = get_logger(__name__)


class RushTaskStatus(Enum):
    """
    刷量任务状态
    """

    # 任务已创建
    CREATED = "created"
    # 任务已启动
    STARTED = "started"
    # 任务已完成
    COMPLETED = "completed"
    # 任务已取消
    CANCELED = "canceled"
    # 任务已失败
    FAILED = "failed"


class RushTaskStage(Enum):
    """
    刷量任务阶段
    """

    # 准备
    prepare = "prepare-准备-0"
    # 限价单开仓阶段
    open_limit = "open_limit-限价开仓-1"
    # 市价单开仓阶段
    open_market = "open_market-市价开仓-2"
    # 持仓阶段
    hold = "hold-持仓等待-3"
    # 限价单平仓阶段
    close_limit = "close_limit-限价平仓-4"
    # 市价单平仓阶段
    close_market = "close_market-市价平仓-5"
    # 任务已完成
    completed = "completed-任务完成-6"


class RushTaskLog(BaseModel):
    """
    刷量任务阶段日志类
    """

    timestamp: int
    preview_status: RushTaskStatus
    current_status: RushTaskStatus
    preview_stage: RushTaskStage
    current_stage: RushTaskStage
    message: str | None = None


class RushTask(BaseModel):
    """
    刷量任务类
    """

    # 任务ID
    task_id: str
    # 任务状态
    status: RushTaskStatus = RushTaskStatus.CREATED
    # 任务阶段
    stage: RushTaskStage = RushTaskStage.prepare
    # 交易对
    symbol: str
    # 第一个账户
    first_account: ExchangeAccount
    # 第二个账户
    second_account: ExchangeAccount
    # 已成交订单列表
    filled_orders: list[FilledOrder] = []
    # 未成交订单映射
    open_orders: dict[int, Order] = {}
    # 已取消订单列表
    cancel_orders: list[CanceledOrder] = []
    # 任务日志列表
    logs: list[RushTaskLog] = []

    def change_status(self, *, status: RushTaskStatus) -> None:
        """
        改变任务状态
        :param status: 任务状态
        :return: None
        """
        if self.status == status:
            return
        preview_status = self.status
        message = f"任务 [{self.task_id}] 状态从 {preview_status.value} 变更为 {status.value}"
        self.status = status
        logger.info(message)
        self.logs.append(
            RushTaskLog(
                timestamp=now(),
                preview_status=preview_status,
                current_status=status,
                preview_stage=self.stage,
                current_stage=self.stage,
                message=message,
            )
        )

    def change_stage(self, *, stage: RushTaskStage) -> None:
        """
        改变任务阶段
        :param stage: 任务阶段
        :return: None
        """
        if self.stage == stage:
            return
        preview_stage = self.stage
        message = f"任务 [{self.task_id}] 阶段从 {preview_stage.value} 变更为 {stage.value}"
        self.stage = stage
        logger.info(message)

    @staticmethod
    async def create(*, symbol: str, first_account: ExchangeAccount, second_account: ExchangeAccount) -> "RushTask":
        """
        创建任务
        :param symbol: 交易对
        :param first_account: 第一个账户
        :param second_account: 第二个账户
        :return: RushTask
        """
        task = RushTask(
            task_id=uuid.uuid4().hex,
            symbol=symbol,
            first_account=first_account,
            second_account=second_account,
        )
        first_account.running_tasks[task.task_id] = task
        second_account.running_tasks[task.task_id] = task
        return task

    def filled_order_callback(self, *, filled_result: dict):
        """
        已成交订单回调
        :param filled_result: 已成交订单结果
        :return: None
        """
        filled_result_order: dict = filled_result.get("o")
        if filled_result_order is None:
            return
        order_id: str = filled_result_order.get("i")
        if order_id is None:
            return
        if order_id not in self.open_orders.keys():
            return
        order = self.open_orders.get(order_id)
        if order is None:
            return
        filled_order = FilledOrder.from_order(filled_result=filled_result, order=order)
        self.filled_orders.append(filled_order)
        # 从未成交订单映射中移除已成交订单
        self.open_orders.pop(order_id)
        if order.hold_type == OrderHoldType.open:
            # 开仓限价单成交，取消另外一边的限价开仓挂单，改成市价单开仓立即成交
            self.change_stage(stage=RushTaskStage.open_market)
            asyncio.create_task(self.open_market())
        else:
            # 平仓限价单成交，取消另外一边的限价平仓挂单，改成市价单平仓立即成交
            self.change_stage(stage=RushTaskStage.close_market)
            asyncio.create_task(self.close_market())

    async def open_market(self) -> None:
        """
        开仓限价单成交后执行
        将另外一边的订单改为市价单开仓立即成交
        阶段2：市价开仓
        :return: None
        """
        if len(self.open_orders) != 1:
            raise ValueError("任务 [{self.task_id}] 开仓限价单成交后执行，将另外一边的订单改为市价单开仓立即成交，但是只有 {} 个未成交订单".format(len(self.open_orders)))
        if len(self.filled_orders) != 1:
            raise ValueError("任务 [{self.task_id}] 开仓限价单成交后执行，将另外一边的订单改为市价单开仓立即成交，但是只有 {} 个已成交订单".format(len(self.filled_orders)))

        open_order = self.open_orders[0]
        open_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_order.account_id]
        if len(open_order_accounts) != 1:
            raise ValueError("任务 [{self.task_id}] 开仓限价单成交后执行，将另外一边的订单改为市价单开仓立即成交，但是找到 {} 个账户".format(len(open_order_accounts)))
        open_order_account = open_order_accounts[0]
        canceled_order = await open_order_account.cancel(order=open_order)
        self.cancel_orders.append(canceled_order)

        open_market_order_params = canceled_order.order_params.model_copy()
        open_market_order_params.type = OrderType.MARKET
        open_market_order_params.timeInForce = OrderTimeInForce.FOK
        open_market_order_params.timestamp = None
        open_market_order_params.price = None

        self.change_stage(stage=RushTaskStage.open_market)
        open_market_order = await open_order_account.order(params=open_market_order_params, holdType=OrderHoldType.close, price_time=now())
        filled_order = FilledOrder.from_order(order=open_market_order)
        self.filled_orders.append(filled_order)
        asyncio.create_task(self.hold())

    async def close_market(self) -> None:
        """
        平仓限价单成交后执行
        将另外一边的订单改为市价单平仓立即成交
        阶段5：市价平仓
        :return: None
        """
        if len(self.open_orders) != 1:
            raise ValueError("任务 [{self.task_id}] 平仓限价单成交后执行，将另外一边的订单改为市价单平仓立即成交，但是只有 {} 个未成交订单".format(len(self.open_orders)))
        if len(self.filled_orders) != 3:
            raise ValueError("任务 [{self.task_id}] 平仓限价单成交后执行，将另外一边的订单改为市价单平仓立即成交，但是只有 {} 个已成交订单".format(len(self.filled_orders)))

        open_order = self.open_orders[0]
        open_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_order.account_id]
        if len(open_order_accounts) != 1:
            raise ValueError("任务 [{self.task_id}] 平仓限价单成交后执行，将另外一边的订单改为市价单平仓立即成交，但是找到 {} 个账户".format(len(open_order_accounts)))
        open_order_account = open_order_accounts[0]
        canceled_order = await open_order_account.cancel(order=open_order)
        self.cancel_orders.append(canceled_order)

        close_market_order_params = canceled_order.order_params.model_copy()
        close_market_order_params.type = OrderType.MARKET
        close_market_order_params.timeInForce = OrderTimeInForce.FOK
        close_market_order_params.timestamp = None
        close_market_order_params.price = None

        self.change_stage(stage=RushTaskStage.close_market)
        close_market_order = await open_order_account.order(params=close_market_order_params, holdType=OrderHoldType.close, price_time=now())
        filled_order = FilledOrder.from_order(order=close_market_order)
        self.filled_orders.append(filled_order)
        self.finish()

    async def hold(self) -> None:
        """
        持仓等待
        阶段3：持仓等待
        :return: None
        """
        picked_account, _ = self.random_exchange_account()
        hold_time = picked_account.account.hold_time
        hold_time_deviation = picked_account.account.hold_time_deviation
        hold_time = hold_time + hold_time * (random.random() * 2 - 1) * hold_time_deviation
        message = f"任务 [{self.task_id}] 持仓等待 {hold_time:.2f} 秒"
        logger.info(message)
        self.change_stage(stage=RushTaskStage.hold)
        await asyncio.sleep(hold_time)

    def random_exchange_account(self) -> tuple[ExchangeAccount, ExchangeAccount]:
        """
        随机选择一个账户
        :return: 账户
        """
        picked_account = random.choice([self.first_account, self.second_account])
        another_account = self.first_account if picked_account == self.second_account else self.second_account
        return picked_account, another_account

    async def close_limit(self) -> None:
        """
        持仓时间到后执行，挂平仓限价单
        阶段4：平仓限价单
        :return: None
        """
        if len(self.open_orders) != 0:
            raise ValueError("任务 [{self.task_id}] 持仓时间到后执行，挂平仓限价单，但是还有 {} 个未成交订单".format(len(self.open_orders)))

        if len(self.filled_orders) != 2:
            raise ValueError("任务 [{self.task_id}] 持仓时间到后执行，挂平仓限价单，但是只有 {} 个已成交订单".format(len(self.filled_orders)))
        open_buy_orders = [order for order in self.filled_orders if order.hold_type == OrderHoldType.open and order.order_params.side == OrderSide.BUY]
        if len(open_buy_orders) != 1:
            raise ValueError("任务 [{self.task_id}] 持仓时间到后执行，挂平仓限价单，但是只有 {} 个开仓限价单".format(len(open_buy_orders)))
        open_buy_order = open_buy_orders[0]

        open_sell_orders = [order for order in self.filled_orders if order.hold_type == OrderHoldType.open and order.order_params.side == OrderSide.SELL]
        if len(open_sell_orders) != 1:
            raise ValueError("任务 [{self.task_id}] 持仓时间到后执行，挂平仓限价单，但是只有 {} 个开仓限价单".format(len(open_sell_orders)))
        open_sell_order = open_sell_orders[0]

        random_account, _ = self.random_exchange_account()
        # 获取盘口指定位置价格
        position_price: PositionPrice = await random_account.get_depth_position(symbol=self.symbol, depth_position=random_account.account.depth_position)

        close_buy_order_params = OrderParams(
            symbol=self.symbol,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            price=position_price.ask_price,
            quantity=open_buy_order.order_params.quantity,
            timeInForce=OrderTimeInForce.GTX,
        )
        close_sell_order_params = OrderParams(
            symbol=self.symbol,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            price=position_price.bid_price,
            quantity=open_sell_order.order_params.quantity,
            timeInForce=OrderTimeInForce.GTX,
        )

        # 找到开仓时对应的账户
        close_buy_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_buy_order.account_id]
        if len(close_buy_order_accounts) != 1:
            raise ValueError("任务 [{self.task_id}] 持仓时间到后执行，挂平仓限价单，但是只有 {} 个账户".format(len(close_buy_order_accounts)))
        close_buy_order_account = close_buy_order_accounts[0]

        close_sell_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_sell_order.account_id]
        if len(close_sell_order_accounts) != 1:
            raise ValueError("任务 [{self.task_id}] 持仓时间到后执行，挂平仓限价单，但是只有 {} 个账户".format(len(close_sell_order_accounts)))
        close_sell_order_account = close_sell_order_accounts[0]

        close_buy_task = asyncio.create_task(close_buy_order_account.order(order_params=close_buy_order_params, holdType=OrderHoldType.close, price_time=position_price.timestamp))
        close_sell_task = asyncio.create_task(close_sell_order_account.order(order_params=close_sell_order_params, holdType=OrderHoldType.close, price_time=position_price.timestamp))
        self.change_stage(stage=RushTaskStage.close_limit)
        results: tuple[Order, Order] = await asyncio.gather(close_buy_task, close_sell_task)
        for order in results:
            self.open_orders[order.order_result["orderId"]] = order


    async def run(self) -> None:
        """
        运行任务
        阶段1：开仓限价单
        :return: None
        """
        self.change_status(status=RushTaskStatus.STARTED)
        random_account, another_account = self.random_exchange_account()
        # 获取盘口指定位置价格
        position_price: PositionPrice = await random_account.get_depth_position(symbol=self.symbol, depth_position=random_account.account.depth_position)

        buy_order_params = OrderParams(
            symbol=self.symbol,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            price=position_price.bid_price,
            timeInForce=OrderTimeInForce.GTX,
        )

        sell_order_params = OrderParams(
            symbol=self.symbol,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            price=position_price.ask_price,
            timeInForce=OrderTimeInForce.GTX,
        )

        buy_task = asyncio.create_task(random_account.order(order_params=buy_order_params, holdType=OrderHoldType.open, price_time=position_price.timestamp))
        sell_task = asyncio.create_task(another_account.order(order_params=sell_order_params, holdType=OrderHoldType.open, price_time=position_price.timestamp))
        self.change_stage(stage=RushTaskStage.open_limit)
        results: tuple[Order, Order] = await asyncio.gather(buy_task, sell_task)
        for order in results:
            self.open_orders[order.order_result["orderId"]] = order

    def finish(self) -> None:
        """
        完成任务
        :return: None
        """
        self.change_status(status=RushTaskStatus.COMPLETED)
        self.change_stage(stage=RushTaskStage.completed)
        # 注销回调
        self.first_account.running_tasks.pop(self.task_id)
        self.second_account.running_tasks.pop(self.task_id)

    def failed(self) -> None:
        """
        失败任务
        :return: None
        """
        self.change_status(status=RushTaskStatus.FAILED)
        # 注销回调
        self.first_account.running_tasks.pop(self.task_id)
        self.second_account.running_tasks.pop(self.task_id)
