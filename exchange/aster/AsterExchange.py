from lib.tools import now
from model.Symbol import Symbol
from lib.Exchange import Exchange
from model.OrderParams import OrderParams
from httpx import AsyncClient
from exchange.aster.AsterAccountV3 import AsterAccountV3
from exchange.aster.AsterAccountV1 import AsterAccountV1
import json
from eth_abi import encode
from web3 import Web3
from eth_account.messages import encode_defunct
from eth_account import Account
import hmac
import hashlib
from urllib.parse import urlencode
from model.PositionPrice import PositionPrice


# 定义所有元素取值转换为字符串
def _trim_dict(my_dict):
    # 假设待删除的字典为d
    for key in my_dict:
        value = my_dict[key]
        if isinstance(value, list):
            new_value = []
            for item in value:
                if isinstance(item, dict):
                    new_value.append(json.dumps(_trim_dict(item)))
                else:
                    new_value.append(str(item))
            my_dict[key] = json.dumps(new_value)
            continue
        if isinstance(value, dict):
            my_dict[key] = json.dumps(_trim_dict(value))
            continue
    my_dict[key] = str(value)
    return my_dict


def sign_v3(*, params: OrderParams, account: AsterAccountV3) -> str:
    """
    签名
    :param params: 下单参数
    :param account: 账户
    :return: 签名
    """
    params_dict = params.model_dump(mode="json")
    _trim_dict(params_dict)
    # 根据ASCII排序生成字符串并移除特殊字符
    json_str = json.dumps(params_dict, sort_keys=True).replace(" ", "").replace("'", '"')

    # 使用WEB3 ABI对生成的字符串和accuser, signer, nonce进行编码
    encoded = encode(["string", "address", "address", "uint256"], [json_str, account.user, account.signer, params.timestamp * 1000])
    # keccak hex
    keccak_hex = Web3.keccak(encoded).hex()
    signable_msg = encode_defunct(hexstr=keccak_hex)
    signed_message = Account.sign_message(signable_message=signable_msg, private_key=account.private_key)
    signature = "0x" + signed_message.signature.hex()
    return signature


base_url: str = "https://fapi.asterdex.com"


class AsterExchange(Exchange):
    """
    Aster交易所数据类
    """

    @staticmethod
    async def exchange_info(*, client: AsyncClient) -> dict:
        """
        获取交易所信息
        :param client: HTTP客户端
        :return: 交易所信息
        GET /fapi/v3/exchangeInfo
        """
        response = await client.get("/fapi/v3/exchangeInfo")
        return response.json()

    @staticmethod
    def sign_v3(*, params: OrderParams, account: AsterAccountV3) -> str:
        """
        签名
        :param params: 下单参数
        :param account: 账户
        :return: 签名
        """
        return sign_v3(params=params, account=account)

    @staticmethod
    async def order_v3(*, client: AsyncClient, params: OrderParams, account: AsterAccountV3) -> dict:
        """
        下单
        :param client: HTTP客户端
        :param params: 下单参数
        :param account: 账户
        :return: 下单结果
        POST /fapi/v3/order
        """
        params_dict = params.model_dump(mode="json")
        params_dict["signature"] = AsterExchange.sign_v3(params=params, account=account)
        params_dict["nonce"] = params.timestamp * 1000
        # params_dict["recvWindow"] = 50000
        params_dict["user"] = account.user
        params_dict["signer"] = account.signer
        headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "PythonApp/1.0"}
        response = await client.post("/fapi/v3/order", data=params_dict, headers=headers)
        # url = "https://fapi.asterdex.com/fapi/v3/order"
        # res = requests.post(url, data=params_dict, headers=headers, proxies=dict(
        #     http="socks5://127.0.0.1:1080",
        #     https="socks5://127.0.0.1:1080",
        # ))
        # res = requests.post(url, data=params_dict, headers=headers )
        return response.json()

    @staticmethod
    async def order_v1(*, client: AsyncClient, params: OrderParams, account: AsterAccountV1) -> dict:
        """
        下单
        :param client: HTTP客户端
        :param params: 下单参数
        :param account: 账户
        :return: 下单结果
        POST /fapi/v1/order
        """
        params_dict = params.model_dump(mode="json")
        data = urlencode(params_dict)
        hmac_obj = hmac.new(account.api_secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256)
        data += f"&signature={hmac_obj.hexdigest()}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "PythonApp/1.0",
            "X-MBX-APIKEY": account.api_key,
        }
        url = "/fapi/v1/order"
        if account.test_mode:
            url = "/fapi/v1/order/test"
        response = await client.post(url, data=data, headers=headers)
        return response.json()

    @staticmethod
    async def get_depth_position(*, client: AsyncClient, symbol: Symbol, position: int) -> PositionPrice:
        """
        获取限价单下单时 使用价格距离盘口的位置
        :param client: HTTP客户端
        :param symbol: 交易对
        :param position: 位置
        :return: 价格距离盘口的位置(ask_price, bid_price)
        """
        limits = [5, 10, 20, 50, 100, 500, 1000]
        limit = 50
        for _limit in limits:
            if position < _limit:
                limit = _limit
                break

        response = await client.get(f"/fapi/v1/depth?symbol={symbol.symbol}&limit={limit}")
        data: dict = response.json()
        asks: list[list[str]] = data.get("asks")
        bids: list[list[str]] = data.get("bids")
        ask_price = asks[position - 1][0]
        bid_price = bids[position - 1][0]
        return PositionPrice(ask_price=ask_price, bid_price=bid_price, timestamp=data.get("T"))

    @staticmethod
    async def delete_order_v1(*, client: AsyncClient, order_id: int, symbol: str, account: AsterAccountV1) -> dict:
        """
        取消订单
        :param client: HTTP客户端
        :param order_id: 订单ID
        :param account: 账户
        :return: 取消订单结果
        DELETE /fapi/v1/order
        """
        params_dict = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": now(),
        }
        data = urlencode(params_dict)
        hmac_obj = hmac.new(account.api_secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256)
        data += f"&signature={hmac_obj.hexdigest()}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "PythonApp/1.0",
            "X-MBX-APIKEY": account.api_key,
        }
        response = await client.delete(f"/fapi/v1/order?{data}", headers=headers)
        return response.json()

    @staticmethod
    async def create_listen_key_v1(*, client: AsyncClient, account: AsterAccountV1) -> dict:
        """
        创建监听键
        :param client: HTTP客户端
        :param account: 账户
        :return: 创建监听键结果
        POST /fapi/v1/listenKey
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "PythonApp/1.0",
            "X-MBX-APIKEY": account.api_key,
        }
        response = await client.post(f"/fapi/v1/listenKey", headers=headers)
        return response.json()

    @staticmethod
    async def refresh_listen_key_v1(*, client: AsyncClient, account: AsterAccountV1) -> dict:
        """
        刷新监听键
        :param client: HTTP客户端
        :param account: 账户
        :return: 刷新监听键结果
        POST /fapi/v1/listenKey
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "PythonApp/1.0",
            "X-MBX-APIKEY": account.api_key,
        }
        await client.put(f"/fapi/v1/listenKey", headers=headers)
