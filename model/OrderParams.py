from abc import ABC
from enum import Enum
from typing import Literal
from pydantic import BaseModel

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"

class OrderTimeInForce(str, Enum):
    GTC = "GTC"  # 成交为止, 一直有效
    IOC = "IOC"  # 无法立即成交(吃单)的部分就撤销
    FOK = "FOK"  # 无法全部立即成交就撤销
    GTX = "GTX"  # 无法成为挂单方就撤销

class OrderParams(BaseModel):
    symbol: str
    side: OrderSide
    type: OrderType
    timestamp: int
    price: str | None = None
    quantity: str | None = None
    timeInForce: OrderTimeInForce  = OrderTimeInForce.GTC
