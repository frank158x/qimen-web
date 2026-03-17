#!/bin/bash

echo "🔮 正在连接天机，安装所需环境..."
pip install -r requirements.txt

echo "🔓 正在向 GitHub 索要公网权限..."
# 这行代码的意思是：强制把当前云电脑的 5000 端口切换为公开状态
gh codespace ports visibility 5000:public -c $CODESPACE_NAME

echo "✨ 通道已打通！正在启动奇门遁甲服务..."
python app.py
