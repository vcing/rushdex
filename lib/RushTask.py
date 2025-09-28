import asyncio
from enum import Enum
from unittest import result
import uuid
from pydantic import BaseModel, ConfigDict
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


class RushTaskStatus(str, Enum):
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


class RushTaskStage(str, Enum):
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

    model_config = ConfigDict(use_enum_values=True)  # Pydantic v2
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

    model_config = ConfigDict(use_enum_values=True)  # Pydantic v2
    # 任务ID
    id: str
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
    # 过期订单 id 列表，因为有可能ws先收到下单时订单过期，下单的http函数慢一步
    # 所以 下单完成后 要检查刚才的订单的订单ID是不是在这个列表中。
    # 如果存在，则直接进行处理限价单下单失败流程
    expired_order_id_map: dict[str, dict] = {}

    def change_status(self, *, status: RushTaskStatus) -> None:
        """
        改变任务状态
        :param status: 任务状态
        :return: None
        """
        if self.status == status:
            return
        preview_status = self.status
        message = f"任务 [{self.id}] 状态从 {preview_status.value} 变更为 {status.value}"
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
        message = f"任务 [{self.id}] 阶段从 {preview_stage.value} 变更为 {stage.value}"
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
            id=uuid.uuid4().hex,
            symbol=symbol,
            first_account=first_account,
            second_account=second_account,
        )
        return task

    async def handle_failed_limit_order(self, *, order_id: str, message: dict) -> None:
        """
        处理失败的限价单
        :param order_id: 订单ID
        :return: None
        """
        # 将该订单移动到已取消订单列表
        order = self.open_orders.get(order_id)
        if order is None:
            self.expired_order_id_map[order_id] = message
            return
        self.cancel_orders.append(CanceledOrder.from_order(order=order, cancel_result=message))
        # 从未成交订单映射中移除已取消订单
        self.open_orders.pop(order_id)
        account_id = order.account_id
        account = self.first_account if account_id == self.first_account.account.id else self.second_account

        # 获取订单参数，改成市价单
        order_params = order.order_params.model_copy()
        order_params.type = OrderType.MARKET
        order_params.timeInForce = None
        order_params.timestamp = now()
        order_params.price = None
        # 重新提交订单
        new_order: Order = await account.order(params=order_params, hold_type=order.hold_type, price_time=order.price_time)
        new_order_id = str(new_order.order_result["orderId"])
        self.open_orders[new_order_id] = new_order
        # 这里不能使用ws回调了 直接继续执行下一步 和正常限价单回调的 ws 后续操作一样
        self.limit_order_on_filled(order=new_order, message={"message": "原限价单GTX下单失败，改为市价单直接下单", result: message})

    def order_update_callback(self, *, message: dict):
        """
        已成交订单回调
        :param filled_result: 已成交订单结果
        :return: None
        """
        update_order: dict = message.get("o")
        if update_order is None:
            return
        current_status: str = update_order.get("X")
        if current_status is None:
            return
        if current_status not in ["FILLED", "EXPIRED"]:
            return
        order_id: str = str(update_order.get("i"))
        if order_id is None:
            return
        if current_status == "EXPIRED":
            logger.info(f"任务 [{self.id}] 订单 {order_id} 状态更新为 {current_status}, 重新下市价单")
            asyncio.create_task(self.handle_failed_limit_order(order_id=order_id, message=message))
            return
        if order_id not in self.open_orders.keys():
            return
        order = self.open_orders.get(order_id)
        if order is None:
            return

        self.limit_order_on_filled(order=order, message=message)

    def limit_order_on_filled(self, *, order: Order, message: dict) -> None:
        """
        处理已成交限价单
        :param order_id: 订单ID
        :param message: 已成交订单结果
        :return: None
        """
        order_id = str(order.order_result["orderId"])
        logger.info(f"任务 [{self.id}] {order.hold_type.value} 阶段挂单成交 {order_id} 状态更新为 FILLED")
        filled_order = FilledOrder.from_order(filled_result=message, order=order)
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
        # if len(self.open_orders) != 1:
        #     raise ValueError(f"任务 [{self.id}] 开仓限价单成交后执行，将另外一边的订单改为市价单开仓立即成交，但是只有 {len(self.open_orders)} 个未成交订单")
        # if len(self.filled_orders) != 1:
        #     raise ValueError(f"任务 [{self.id}] 开仓限价单成交后执行，将另外一边的订单改为市价单开仓立即成交，但是只有 {len(self.filled_orders)} 个已成交订单")
        if len(self.open_orders) == 0:
            # 两边同时成交
            logger.info(f"任务 [{self.id}] 开仓限价单两边同时成交")
            # 竞争一个 进入下一阶段
            if self.stage != RushTaskStage.hold:
                logger.info(f"任务 [{self.id}] 开仓限价单两边同时成交, 进入下一阶段")
                self.change_stage(stage=RushTaskStage.hold)
                asyncio.create_task(self.hold())
            else:
                logger.info(f"任务 [{self.id}] 开仓限价单两边同时成交, 已经处于下一阶段，不做处理")
            return

        open_order_id = list(self.open_orders.keys())[0]
        open_order = self.open_orders[open_order_id]
        open_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_order.account_id]
        if len(open_order_accounts) != 1:
            raise ValueError(f"任务 [{self.id}] 开仓限价单成交后执行，将另外一边的订单改为市价单开仓立即成交，但是找到 {len(open_order_accounts)} 个账户")
        open_order_account = open_order_accounts[0]
        canceled_order = await open_order_account.cancel(order=open_order)
        self.open_orders.pop(open_order_id)
        self.cancel_orders.append(canceled_order)

        open_market_order_params = canceled_order.order_params.model_copy()
        open_market_order_params.type = OrderType.MARKET
        open_market_order_params.timeInForce = None
        open_market_order_params.timestamp = now()
        open_market_order_params.price = None

        self.change_stage(stage=RushTaskStage.open_market)
        open_market_order = await open_order_account.order(params=open_market_order_params, hold_type=OrderHoldType.open, price_time=now())
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
        # if len(self.open_orders) != 1:
        #     raise ValueError(f"任务 [{self.id}] 平仓限价单成交后执行，将另外一边的订单改为市价单平仓立即成交，但是只有 {len(self.open_orders)} 个未成交订单")
        # if len(self.filled_orders) != 3:
        #     raise ValueError(f"任务 [{self.id}] 平仓限价单成交后执行，将另外一边的订单改为市价单平仓立即成交，但是只有 {len(self.filled_orders)} 个已成交订单")
        if len(self.open_orders) == 0:
            # 两边同时成交
            logger.info(f"任务 [{self.id}] 平仓限价单两边同时成交")
            # 竞争一个 进入下一阶段
            if self.stage != RushTaskStage.completed:
                logger.info(f"任务 [{self.id}] 平仓限价单两边同时成交, 进入下一阶段")
                self.change_stage(stage=RushTaskStage.completed)
                self.finish()
            else:
                logger.info(f"任务 [{self.id}] 平仓限价单两边同时成交, 已经处于下一阶段，不做处理")
            return

        open_order_id = list(self.open_orders.keys())[0]
        open_order = self.open_orders[open_order_id]
        open_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_order.account_id]
        if len(open_order_accounts) != 1:
            raise ValueError(f"任务 [{self.id}] 平仓限价单成交后执行，将另外一边的订单改为市价单平仓立即成交，但是找到 {len(open_order_accounts)} 个账户")
        open_order_account = open_order_accounts[0]
        canceled_order = await open_order_account.cancel(order=open_order)
        self.open_orders.pop(open_order_id)
        self.cancel_orders.append(canceled_order)

        close_market_order_params = canceled_order.order_params.model_copy()
        close_market_order_params.type = OrderType.MARKET
        close_market_order_params.timeInForce = None
        close_market_order_params.timestamp = now()
        close_market_order_params.price = None

        self.change_stage(stage=RushTaskStage.close_market)
        close_market_order = await open_order_account.order(params=close_market_order_params, hold_type=OrderHoldType.close, price_time=now())
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
        message = f"任务 [{self.id}] 持仓等待 {hold_time:.2f} 秒"
        logger.info(message)
        self.change_stage(stage=RushTaskStage.hold)
        await asyncio.sleep(hold_time)
        asyncio.create_task(self.close_limit())

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
            raise ValueError(f"任务 [{self.id}] 持仓时间到后执行，挂平仓限价单，但是还有 {len(self.open_orders)} 个未成交订单")

        if len(self.filled_orders) != 2:
            raise ValueError(f"任务 [{self.id}] 持仓时间到后执行，挂平仓限价单，但是只有 {len(self.filled_orders)} 个已成交订单")
        open_buy_orders = [order for order in self.filled_orders if order.hold_type == OrderHoldType.open and order.order_params.side == OrderSide.BUY]
        if len(open_buy_orders) != 1:
            raise ValueError(f"任务 [{self.id}] 持仓时间到后执行，挂平仓限价单，但是只有 {len(open_buy_orders)} 个开仓 {OrderSide.BUY.value} 单")
        open_buy_order = open_buy_orders[0]

        open_sell_orders = [order for order in self.filled_orders if order.hold_type == OrderHoldType.open and order.order_params.side == OrderSide.SELL]
        if len(open_sell_orders) != 1:
            raise ValueError(f"任务 [{self.id}] 持仓时间到后执行，挂平仓限价单，但是只有 {len(open_sell_orders)} 个开仓 {OrderSide.SELL.value} 单")
        open_sell_order = open_sell_orders[0]

        random_account, _ = self.random_exchange_account()
        # 获取盘口指定位置价格
        position_price: PositionPrice = await random_account.get_depth_position(symbol=self.symbol, position=random_account.account.depth_position)

        close_buy_order_params = OrderParams(
            symbol=self.symbol,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            price=position_price.ask_price,
            quantity=open_buy_order.order_params.quantity,
            timeInForce=OrderTimeInForce.GTX,
            timestamp=now(),
        )
        close_sell_order_params = OrderParams(
            symbol=self.symbol,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            price=position_price.bid_price,
            quantity=open_sell_order.order_params.quantity,
            timeInForce=OrderTimeInForce.GTX,
            timestamp=now(),
        )

        # 找到开仓时对应的账户
        close_buy_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_buy_order.account_id]
        if len(close_buy_order_accounts) != 1:
            raise ValueError(f"任务 [{self.id}] 持仓时间到后执行，挂平仓限价单，但是只有 {len(close_buy_order_accounts)} 个账户")
        close_buy_order_account = close_buy_order_accounts[0]

        close_sell_order_accounts = [account for account in [self.first_account, self.second_account] if account.account.id == open_sell_order.account_id]
        if len(close_sell_order_accounts) != 1:
            raise ValueError(f"任务 [{self.id}] 持仓时间到后执行，挂平仓限价单，但是只有 {len(close_sell_order_accounts)} 个账户")
        close_sell_order_account = close_sell_order_accounts[0]

        close_buy_task = asyncio.create_task(close_buy_order_account.order(params=close_buy_order_params, hold_type=OrderHoldType.close, price_time=position_price.timestamp))
        close_sell_task = asyncio.create_task(close_sell_order_account.order(params=close_sell_order_params, hold_type=OrderHoldType.close, price_time=position_price.timestamp))
        self.change_stage(stage=RushTaskStage.close_limit)
        results: tuple[Order, Order] = await asyncio.gather(close_buy_task, close_sell_task, return_exceptions=True)
        for order in results:
            if isinstance(order, Exception):
                logger.error(f"任务 [{self.id}] 平仓限价单失败，异常信息：{order}")
                self.failed()
                return
            order_id = str(order.order_result["orderId"])
            self.open_orders[order_id] = order
            if order_id in self.expired_order_id_map.keys():
                await self.handle_failed_limit_order(order_id=order_id, message=self.expired_order_id_map[order_id])

    async def run(self) -> None:
        """
        运行任务
        阶段1：开仓限价单
        :return: None
        """
        self.change_status(status=RushTaskStatus.STARTED)
        random_account, another_account = self.random_exchange_account()
        # 获取盘口指定位置价格
        position_price: PositionPrice = await random_account.get_depth_position(symbol=self.symbol, position=random_account.account.depth_position)

        buy_order_params = OrderParams(symbol=self.symbol, side=OrderSide.BUY, type=OrderType.LIMIT, price=position_price.bid_price, timeInForce=OrderTimeInForce.GTX, timestamp=now())

        sell_order_params = OrderParams(symbol=self.symbol, side=OrderSide.SELL, type=OrderType.LIMIT, price=position_price.ask_price, timeInForce=OrderTimeInForce.GTX, timestamp=now())

        buy_task = asyncio.create_task(random_account.order(params=buy_order_params, hold_type=OrderHoldType.open, price_time=position_price.timestamp))
        sell_task = asyncio.create_task(another_account.order(params=sell_order_params, hold_type=OrderHoldType.open, price_time=position_price.timestamp))
        self.change_stage(stage=RushTaskStage.open_limit)
        results: tuple[Order, Order] = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
        for order in results:
            if isinstance(order, Exception):
                logger.error(f"任务 [{self.id}] 开仓限价单失败，异常信息：{order}")
                self.failed()
                return
            order_id = str(order.order_result["orderId"])
            self.open_orders[order_id] = order
            if order_id in self.expired_order_id_map.keys():
                await self.handle_failed_limit_order(order_id=order_id, message=self.expired_order_id_map[order_id])

    def finish(self) -> None:
        """
        完成任务
        :return: None
        """
        self.change_status(status=RushTaskStatus.COMPLETED)
        self.change_stage(stage=RushTaskStage.completed)

    def failed(self) -> None:
        """
        失败任务
        :return: None
        """
        self.change_status(status=RushTaskStatus.FAILED)
