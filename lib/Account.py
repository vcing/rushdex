import uuid
from pydantic import BaseModel
import config


class Account(BaseModel):
    """
    账户数据类
    """
    id: str
    # 限价单下单时 使用价格距离盘口的位置
    depth_position: int = config.depth_position
    # 目标下单金额
    target_amount: int = config.target_amount
    # 下单金额偏差
    amount_deviation: float = config.amount_deviation
    # 持仓时间
    hold_time: int = config.hold_time
    # 持仓时间偏差
    hold_time_deviation: float = config.hold_time_deviation
    # ip代理
    proxy: str | None = None

    