from lib.Account import Account

class AsterAccountV3(Account):
    """
    Aster账户数据类
    user	主账户钱包地址
    signer	API钱包地址
    privateKey	API钱包私钥
    """
    user: str
    signer: str
    private_key: str