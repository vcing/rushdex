from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict
from lib.Account import Account
from model.PositionPrice import PositionPrice
from model.Order import Order, OrderHoldType
from model.CanceledOrder import CanceledOrder
from model.Symbol import Symbol
from httpx import AsyncClient
from model.OrderParams import OrderParams



class ExchangeAccount(BaseModel, ABC):
    """
    交易所账户数据类
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)  # 新增这一行

    # 账户信息
    account: Account = None
    # http 客户端
    client: AsyncClient = None
    # 交易对列表
    symbols: dict[str, Symbol] = {}

    @abstractmethod
    async def get_depth_position(self, *, symbol: str) -> PositionPrice:
        """
        获取盘口指定位置价格
        :param symbol: 交易对
        :return: PositionPrice
        """
        pass

    @abstractmethod
    async def order(self, *, params: OrderParams, holdType: OrderHoldType, price_time: int) -> Order:
        """
        下单
        """
        pass

    @abstractmethod
    async def cancel(self, *, order: Order) -> CanceledOrder:
        """
        取消订单
        """
        pass