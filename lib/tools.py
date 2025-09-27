import time

def format_to_stepsize(number: float, step_size: str) -> str:
    """
    将数字格式化为符合stepSize规则的字符串
    
    Args:
        number: 要格式化的浮点数
        step_size: 步长字符串，如"0.00100000"
        
    Returns:
        符合步长精度要求的数字字符串
    """
    # 解析stepSize获取小数位数
    if '.' in step_size:
        decimal_part = step_size.split('.')[1].rstrip('0')
        # 如果小数部分全是0，取原始长度
        if not decimal_part:
            decimal_places = len(step_size.split('.')[1])
        else:
            decimal_places = len(decimal_part)
    else:
        decimal_places = 0  # 没有小数部分
    
    # 四舍五入到指定小数位数
    rounded_number = round(number, decimal_places)
    
    # 格式化为指定小数位数的字符串
    # 确保不会用科学计数法表示
    format_str = f"%.{decimal_places}f" if decimal_places > 0 else "%d"
    formatted_str = format_str % rounded_number
    
    return formatted_str

def now() -> int:
    """
    获取当前时间戳
    :return: 当前时间戳
    """
    return int(time.time() * 1000)