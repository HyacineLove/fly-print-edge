#!/bin/bash
# Edge 服务启动脚本（本地）
# 使用方法: ./start.sh [--setup] [--clean]

set -e

VENV_DIR="venv"

echo "========================================"
echo "  FlyPrint Edge 服务启动"
echo "========================================"
echo ""

# 解析参数
SETUP=false
CLEAN=false
for arg in "$@"; do
    case $arg in
        --setup)
            SETUP=true
            ;;
        --clean)
            CLEAN=true
            SETUP=true
            ;;
    esac
done

# 清理虚拟环境
if [ "$CLEAN" = true ]; then
    echo "清理现有虚拟环境..."
    if [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR"
        echo "✓ 虚拟环境已清理"
    fi
fi

# 检查虚拟环境是否存在
if [ ! -d "$VENV_DIR" ] || [ "$SETUP" = true ]; then
    echo "[1/3] 创建虚拟环境..."
    
    # 检查Python是否安装
    if ! command -v python3 &> /dev/null; then
        echo "✗ 未找到Python3，请先安装Python 3.8+"
        exit 1
    fi
    
    python_version=$(python3 --version)
    echo "  Python版本: $python_version"
    
    # 创建虚拟环境
    python3 -m venv venv
    echo "✓ 虚拟环境创建成功"
    
    echo ""
    echo "[2/3] 安装依赖包..."
    
    # 激活虚拟环境
    source "$VENV_DIR/bin/activate"
    
    # 升级pip
    echo "  升级pip..."
    python -m pip install --upgrade pip -q
    
    # 安装依赖
    echo "  安装requirements.txt依赖..."
    pip install -r requirements.txt -q
    
    echo "✓ 依赖安装成功"
    
    echo ""
    echo "[3/3] 虚拟环境设置完成！"
    echo ""
    
    if [ "$SETUP" = true ]; then
        echo "========================================"
        echo "  设置完成！"
        echo "========================================"
        echo ""
        echo "使用以下命令启动Edge服务:"
        echo "  ./start.sh"
        echo ""
        exit 0
    fi
fi

# 检查配置文件
if [ ! -f "config.json" ]; then
    echo "⚠️  警告: config.json 不存在"
    [ -f "config.example.json" ] && echo "提示: 可复制 config.example.json 为 config.json 后修改 cloud.client_secret 等"
    echo ""
    echo "请先配置 Edge 节点:"
    echo "1. 登录 Cloud 管理后台 (http://localhost)"
    echo "2. 创建 OAuth2 客户端"
    echo "3. 复制 Client ID 和 Secret"
    echo "4. 更新 config.json 中的认证信息"
    echo ""
    read -p "按 Enter 继续启动（可能会失败）"
fi

# 启动Edge服务
echo "启动Edge服务..."
echo ""
echo "虚拟环境: $(pwd)/$VENV_DIR"
echo "工作目录: $(pwd)"
if [ -f "config.json" ]; then
    echo "配置文件: ✓ config.json"
else
    echo "配置文件: ✗ 缺失"
fi
echo ""
echo "========================================"
echo "  Edge服务运行中..."
echo "  按 Ctrl+C 停止服务"
echo "========================================"
echo ""

# 激活虚拟环境并运行
source "$VENV_DIR/bin/activate"
python main.py
