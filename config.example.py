import warnings

# 模拟模式 不会真正的下单 但是会模拟下单成功
simulate: bool = True

# 需要刷的交易对
symbols: list[str] = ["BTCUSDT", "ETHUSDT"]
accounts: list[dict] = []

# 添加账户
accounts.append(dict(
    api_key="填上你账号的apiKey",
    api_secret="填上你账号的apiSecret",
    exchange="aster"
))

accounts.append(dict(
    api_key="填上你账号的apiKey",
    api_secret="填上你账号的apiSecret",
    exchange="aster"
))

# 最大并发任务数量 默认为 账户数量/2 * 交易对数量
max_concurrent_tasks: int = int(len(accounts) / 2) * len(symbols)
# 你也可以手动修改成一个更小的值
# max_concurrent_tasks: int = 1


# 限价单下单时 使用价格距离盘口的位置 aster 交易所 可以在这里查看 http://fapi.asterdex.com/fapi/v1/depth?symbol=BTCUSDT&limit=500
depth_position: int = 50
# 目标下单金额
target_amount: int = 100
# 下单金额偏差 0.01 表示 1%
amount_deviation: float = 0.01
# 持仓时间
hold_time: int = 60 * 5 # 默认五分钟
# 持仓时间偏差 0.01 表示 1%
hold_time_deviation: float = 0.01

assert len(accounts) >= 2, "至少需要两个账户"
assert len(symbols) >= 1, "至少需要一个交易对"
assert max_concurrent_tasks <= int(len(accounts) / 2) * len(symbols), "最大并发任务数量不能超过 账户数量/2 * 交易对数量"
assert depth_position > 0, "depth_position 必须大于 0"
assert depth_position <= 500, "depth_position 必须小于等于 500"
assert target_amount >= 10, "target_amount 必须大于等于 10"


RushEngineInterval = 1 # 引擎运行检查间隔，单位秒, 如果要高频刷，需要调低这个值

if RushEngineInterval < 0.01:
    warnings.warn("如果 RushEngineInterval 小于 0.01, 主循环会非常频繁, 占用CPU资源，可能导致交易任务无法执行。")
    
