from abc import ABC, abstractmethod
from model.Symbol import Symbol
from pydantic import BaseModel
from httpx import AsyncClient



class Exchange(BaseModel, ABC):
    """
    交易所数据类
    """

    @abstractmethod
    async def get_depth_position(self, *, client: AsyncClient, symbol: str, position: int) -> (str, str):
        pass