from enum import Enum
from pydantic import BaseModel
from model.OrderParams import OrderParams


class OrderHoldType(Enum):
    """
    订单持仓目的类型枚举类
    """

    # 开仓订单
    open = "open"
    # 平仓订单
    close = "close"


class Order(BaseModel):
    """
    订单数据类
    """

    # 价格时间
    price_time: int
    # 持仓目的类型
    hold_type: OrderHoldType
    # 下单原始数据
    order_params: OrderParams
    # 下单结果数据
    order_result: dict | None = None
    # 账户id
    account_id: str
