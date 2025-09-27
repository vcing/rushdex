from random import random
from exchange.aster.AsterAccountV1 import AsterAccountV1
from exchange.aster.AsterExchange import AsterExchange, base_url
from httpx import AsyncClient
from lib.logger import get_logger
from model.Symbol import Symbol
from model.OrderParams import OrderParams
from lib.tools import format_to_stepsize
from model.Order import Order, OrderHoldType
from model.CanceledOrder import CanceledOrder
from model.PositionPrice import PositionPrice
import websockets
from lib.ExchangeAccount import ExchangeAccount
from typing import Callable
import asyncio


logger = get_logger(__name__)


class AsterExchangeAccountV1(ExchangeAccount):
    """
    币安V1交易所账户类
    """

    account: AsterAccountV1 = None
    exchange_info: dict = None

    async def init(self, *, account: AsterAccountV1, callback: Callable[[str], None]) -> asyncio.Task:
        """
        初始化交易所账户
        """
        self.account = account
        self.client = AsyncClient(proxy=self.account.proxy, base_url=base_url)

        await self.init_exchange_info()
        listen_key = await self.get_listen_key()
        refresh_task = asyncio.create_task(self.refresh_listen_key())
        ws_task = asyncio.create_task(self.init_ws(listen_key=listen_key, callback=callback))
        return asyncio.gather(refresh_task, ws_task)

    async def init_exchange_info(self):
        """
        初始化交易所信息
        """
        self.exchange_info = await AsterExchange.exchange_info(client=self.client)
        self.generate_symbols()

    def generate_symbols(self):
        """
        生成交易对列表
        """
        for symbol_info in self.exchange_info["symbols"]:
            symbol = symbol_info["symbol"]
            filters = symbol_info["filters"]
            tick_size: str = None
            step_size: str = None
            for filter in filters:
                if filter["filterType"] == "PRICE_FILTER":
                    tick_size = filter["tickSize"]
                if filter["filterType"] == "LOT_SIZE":
                    step_size = filter["stepSize"]
            self.symbols[symbol] = Symbol(symbol=symbol, tick_size=tick_size, step_size=step_size)

    async def order(self, *, params: OrderParams, holdType: OrderHoldType, price_time: int) -> Order:
        """
        下单
        """
        if params.quantity is None:
            if params.price is None:
                raise ValueError("price is None")
            target_amount = self.account.target_amount
            # 偏移目标金额
            deviation_amount = target_amount * self.account.amount_deviation * (random() * 2 - 1)
            # 实际下单金额
            target_amount += deviation_amount
            # 实际下单数量
            params.quantity = format_to_stepsize(target_amount / float(params.price), self.symbols[params.symbol].step_size)

        logger.info(f"下单参数: {params.model_dump_json(indent=2)}")

        orderResult = await AsterExchange.order_v1(client=self.client, params=params, account=self.account)
        order = Order(orderParams=params, orderResult=orderResult, holdType=holdType, price_time=price_time, account_id=self.account.id)
        return order

    async def cancel(self, *, order: Order) -> CanceledOrder:
        """
        取消订单
        """
        cancelResult = await AsterExchange.delete_order_v1(client=self.client, account=self.account, symbol=order.order_params.symbol, order_id=order.order_result["orderId"])
        return CanceledOrder.from_order(order=order, cancelResult=cancelResult)

    async def get_depth_position(self, *, symbol: str) -> PositionPrice:
        """
        获取盘口指定位置价格
        :param symbol: 交易对
        :return: ask_price, bid_price
        """
        return await AsterExchange.get_depth_position(client=self.client, symbol=symbol, depth_position=self.account.depth_position)

    async def refresh_listen_key(self):
        """
        刷新监听键
        """
        while True:
            await asyncio.sleep(60 * 30)
            await AsterExchange.refresh_listen_key_v1(client=self.client, account=self.account)

    async def get_listen_key(self) -> str:
        """
        获取listenKey
        :return: listen_key
        """
        data = await AsterExchange.create_listen_key_v1(client=self.client, account=self.account)
        return data["listenKey"]

    async def init_ws(self, *, listen_key: str, callback: Callable[[str], None]):
        """
        初始化websocket
        """
        # 生成listenKey
        # wss://fstream.asterdex.com
        async for ws in websockets.connect(uri=f"wss://fstream.asterdex.com/ws/{listen_key}", proxy=self.account.proxy):
            # 标记账户为就绪
            self.ready = True
            async for message in ws:
                callback(message=message)
