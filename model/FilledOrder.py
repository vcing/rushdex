from model.Order import Order
from model.OrderParams import OrderParams


class FilledOrder(Order):
    """
    成交订单数据类
    """

    # 成交结果数据
    # 市价单没有这个结果
    filled_result: dict | None = None

    @staticmethod
    def from_order(*, order: Order, filled_result: dict | None = None) -> "FilledOrder":
        """
        从订单数据创建成交订单数据
        """
        return FilledOrder(
            **order.__dict__,
            filled_result=filled_result,
        )
