#!/bin/bash
# 初始化conda
eval "$(conda shell.bash hook)"

# 激活环境（假设env是环境名称而不是路径）
conda activate ./env

# 安装依赖
pip install -r requirements.txt