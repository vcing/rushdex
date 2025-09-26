import uuid
from pydantic import BaseModel


class Account(BaseModel):
    """
    账户数据类
    """
    id: str = uuid.uuid4().hex
    # 限价单下单时 使用价格距离盘口的位置
    depth_position: int = 50
    # 目标下单金额
    target_amount: int = 100
    # 下单金额偏差
    amount_deviation: float = 0.01
    # 持仓时间
    hold_time: int = 1000 * 60 * 5 # 默认五分钟
    # 持仓时间偏差
    hold_time_deviation: float = 0.01
    # ip代理
    proxy: str | None = None
    test_mode: bool = False

    