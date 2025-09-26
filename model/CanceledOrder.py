from model.Order import Order


class CanceledOrder(Order):
    """
    已取消订单数据类
    """

    # 取消订单结果数据
    cancel_result: dict

    @staticmethod
    def from_order(*, order: Order, cancel_result: dict) -> "CanceledOrder":
        """
        从订单数据创建已取消订单数据
        """
        return CanceledOrder(
            **order.__dict__,
            cancel_result=cancel_result,
        )
