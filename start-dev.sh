#!/bin/bash

# 开发环境启动脚本
# 使用 .env 文件配置

set -e

echo "=================================="
echo "DocFusion 开发环境启动脚本"
echo "=================================="

# 检查 .env 文件是否存在
if [ ! -f .env ]; then
    echo "⚠️  警告：未找到 .env 文件"
    echo "请先创建 .env 文件并填入真实的 API key"
    echo ""
    echo "步骤："
    echo "1. 复制模板：cp .env.example .env"
    echo "2. 编辑 .env 文件，填入真实的 API key"
    echo "3. 重新运行此脚本"
    exit 1
fi

# 检查 API keys 是否配置
MIMO_API_KEY=$(grep "^MIMO_API_KEY=" .env | cut -d'=' -f2-)
GITEE_AI_API_KEY=$(grep "^GITEE_AI_API_KEY=" .env | cut -d'=' -f2-)

if [ -z "$MIMO_API_KEY" ] || [ "$MIMO_API_KEY" = "your_mimo_api_key_here" ]; then
    echo "❌ 错误：MIMO_API_KEY 未配置或使用默认值"
    echo "请在 .env 文件中填入真实的 MiMO API key"
    exit 1
fi

if [ -z "$GITEE_AI_API_KEY" ] || [ "$GITEE_AI_API_KEY" = "your_gitee_ai_key_here" ]; then
    echo "❌ 错误：GITEE_AI_API_KEY 未配置或使用默认值"
    echo "请在 .env 文件中填入真实的 Gitee AI API key"
    exit 1
fi

echo "✅ 检查通过，API key 已配置"

# 启动数据库服务
echo ""
echo "正在启动数据库服务..."
docker-compose -f docker-compose.dev.yml up -d

echo ""
echo "=================================="
echo "✅ 数据库服务启动成功！"
echo "=================================="
echo ""
echo "数据库访问地址："
echo "  PostgreSQL: localhost:5432"
echo "  Neo4j: localhost:7474 (Web UI), localhost:7687 (Bolt)"
echo "  Qdrant: localhost:6333"
echo ""
echo "接下来："
echo "1. 启动后端服务："
echo "   cd backend"
echo "   python -m venv venv"
echo "   source venv/bin/activate  # Linux/Mac"
echo "   # venv\\Scripts\\activate  # Windows"
echo "   pip install -r requirements.txt"
echo "   uvicorn app.main:app --reload --port 8000"
echo ""
echo "2. 启动前端服务："
echo "   cd frontend"
echo "   npm install"
echo "   npm run dev"
echo ""
echo "查看数据库日志："
echo "  docker-compose -f docker-compose.dev.yml logs -f"
echo ""
echo "停止数据库服务："
echo "  docker-compose -f docker-compose.dev.yml down"
echo "=================================="
