from pydantic import BaseModel

class PositionPrice(BaseModel): 
    """
    盘口指定位置价格数据类
    """
    ask_price: str
    bid_price: str
    timestamp: int
