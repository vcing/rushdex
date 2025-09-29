from random import random
import config
from exchange.aster.AsterAccountV1 import AsterAccountV1
from exchange.aster.AsterExchange import AsterExchange, base_url
from httpx import AsyncClient
from lib.logger import get_logger
from model.Symbol import Symbol
from model.OrderParams import OrderParams, OrderSide, OrderTimeInForce, OrderType
from lib.tools import format_to_stepsize, now
from model.Order import Order, OrderHoldType
from model.CanceledOrder import CanceledOrder
from model.PositionPrice import PositionPrice
import websockets
from websockets.exceptions import ConnectionClosed
from lib.ExchangeAccount import ExchangeAccount
from typing import Callable
import asyncio


logger = get_logger(__name__)


class AsterExchangeAccountV1(ExchangeAccount):
    """
    Aster V1交易所账户类
    """

    account: AsterAccountV1 = None
    exchange_info: dict = None
    ws: websockets.connect = None

    async def init(self, *, account: AsterAccountV1, callback: Callable[[str], None]) -> asyncio.Task:
        """
        初始化交易所账户
        """
        self.account = account
        if self.account.proxy is not None:
            self.client = AsyncClient(proxy=self.account.proxy, base_url=base_url)
        else:
            self.client = AsyncClient(base_url=base_url)

        await self.init_exchange_info()
        listen_key = await self.get_listen_key()
        # 刷新 listenKey 任务
        refresh_task = asyncio.create_task(self.refresh_listen_key())
        # 初始化 WebSocket 连接
        ws_task = asyncio.create_task(self.init_ws(listen_key=listen_key, callback=callback))
        await self.cancel_all_open_orders()
        await self.clear_all_positions()
        return asyncio.gather(refresh_task, ws_task, return_exceptions=True)

    async def close(self):
        """
        关闭交易所账户
        """
        await self.client.aclose()
        if self.ws is not None:
            try:
                await self.ws.close()
            except ConnectionClosed:
                pass

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

    async def order(self, *, params: OrderParams, hold_type: OrderHoldType, price_time: int) -> Order:
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
            # if config.simulate:
            #     self.symbols[params.symbol].step_size = "0.0001"
            if (target_amount / float(params.price)) < float(self.symbols[params.symbol].step_size):
                min_usdt = float(self.symbols[params.symbol].step_size) * float(params.price)
                raise ValueError(f"下单金额 {target_amount} 小于{params.symbol}步进金额(最小下单金额) {self.symbols[params.symbol].step_size} {params.symbol} 约 {min_usdt} USDT")
            # 实际下单数量
            params.quantity = format_to_stepsize(target_amount / float(params.price), self.symbols[params.symbol].step_size)

        # logger.info(f"下单参数: {params.model_dump_json(indent=2, exclude_none=True)}")

        order_result = await AsterExchange.order_v1(client=self.client, params=params, account=self.account)
        if order_result.get("code") is not None:
            raise ValueError(f"下单失败: {order_result}")
        order = Order(order_params=params, order_result=order_result, hold_type=hold_type, price_time=price_time, account_id=self.account.id)
        return order

    async def cancel(self, *, order: Order) -> CanceledOrder:
        """
        取消订单
        """
        cancel_result = await AsterExchange.delete_order_v1(client=self.client, account=self.account, symbol=order.order_params.symbol, order_id=order.order_result["orderId"])
        # 模拟模式 不抛出取消订单异常
        if cancel_result.get("code") is not None and not config.simulate:
            raise ValueError(f"取消订单失败: {cancel_result}")
        return CanceledOrder.from_order(order=order, cancel_result=cancel_result)

    async def get_all_open_orders(self) -> dict:
        """
        获取所有未成交订单
        :return: 获取所有未成交订单结果
        """
        logger.info(f"账户 {self.account.id} 获取所有未成交订单")
        open_orders = await AsterExchange.all_open_orders_v1(client=self.client, account=self.account)
        if not isinstance(open_orders, list):
            raise ValueError(f"账户 {self.account.id} 获取所有未成交订单失败: {open_orders}")
        return open_orders

    async def get_all_open_orders_symbol_set(self) -> set:
        """
        获取所有未成交订单交易对集合
        :return: 所有未成交订单交易对集合
        """
        open_orders = await self.get_all_open_orders()
        return set(map(lambda order: order["symbol"], open_orders))

    async def cancel_all_open_orders(self) -> dict:
        """
        取消所有未成交订单
        :return: 取消所有未成交订单结果
        """
        logger.info(f"账户 {self.account.id} 取消所有未成交订单")
        symbol_set = await self.get_all_open_orders_symbol_set()
        cancel_result = {}
        for symbol in symbol_set:
            cancel_result[symbol] = await self.cancel_all(symbol=symbol)
        return cancel_result

    async def cancel_all(self, *, symbol: str) -> dict:
        """
        取消所有未成交订单
        :param symbol: 交易对
        """
        logger.info(f"账户 {self.account.id} 取消所有未成交订单: {symbol}")
        cancel_result = await AsterExchange.delete_all_open_orders_v1(client=self.client, account=self.account, symbol=symbol)
        if cancel_result.get("code") is not None:
            logger.error(f"账户 {self.account.id} 取消所有未成交订单失败: {cancel_result}")
            raise ValueError(f"账户 {self.account.id} 取消所有未成交订单失败: {cancel_result}")
        return cancel_result

    async def get_account_info(self) -> dict:
        """
        获取账户信息V4
        :return: 账户信息V4结果
        """
        data = await AsterExchange.account_v4(client=self.client, account=self.account)
        data.pop("assets")
        positions = data.get("positions", [])
        data["positions"] = list(filter(lambda position: float(position["notional"]) != 0, positions))
        return data

    async def set_leverage(self, *, symbol: str, leverage: int):
        """
        设置杠杆
        :param symbol: 交易对
        :param leverage: 杠杆
        """
        logger.info(f"账户 {self.account.id} 设置杠杆: {symbol} {leverage}")
        return await AsterExchange.leverage(client=self.client, account=self.account, symbol=symbol, leverage=leverage)

    async def clear_all_positions(self):
        """
        清空所有持仓
        :param symbol: 交易对
        """
        account_info = await self.get_account_info()
        positions = account_info.get("positions", [])
        for position in positions:
            position_amount = float(position["positionAmt"])
            params = OrderParams(
                symbol=position["symbol"],
                type=OrderType.MARKET,
                side=OrderSide.SELL if position_amount > 0 else OrderSide.BUY,
                quantity=str(position["positionAmt"]).replace("-", ""),
                timestamp=now(),
            )
            logger.info(f"账户 {self.account.id} 清仓下单参数: {params.model_dump_json(indent=2, exclude_none=True)}")
            await self.order(params=params, hold_type=OrderHoldType.close, price_time=now())

    async def get_depth_position(self, *, symbol: str, position: int) -> PositionPrice:
        """
        获取盘口指定位置价格
        :param symbol: 交易对
        :return: ask_price, bid_price
        """
        return await AsterExchange.get_depth_position(client=self.client, symbol=symbol, position=position)

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
        初始化websocket并绑定到实例
        """
        uri = f"wss://fstream.asterdex.com/ws/{listen_key}"
        try:
            # 建立连接并将实例保存到self.ws
            self.ws = await websockets.connect(uri, proxy=self.account.proxy)
            self.ready = True
            # 持续监听消息
            async for message in self.ws:
                callback(message=message)  # 调用回调处理消息

        except ConnectionClosed:
            # 连接被关闭时的处理
            self.ws = None
        except Exception as e:
            # 其他异常处理
            logger.error(f"账户 {self.account.id} WebSocket错误: {e}")
            self.ws = None
            raise e
