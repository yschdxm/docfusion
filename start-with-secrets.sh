#!/bin/bash

# Docker secrets 启动脚本
# 用于生产环境部署

set -e

echo "=================================="
echo "DocFusion Docker Secrets 启动脚本"
echo "=================================="

# 检查是否在 Docker 环境中运行
if ! docker info > /dev/null 2>&1; then
    echo "❌ 错误：Docker 未运行或无法访问"
    exit 1
fi

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

# 从 .env 文件读取 API keys
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

# 创建 Docker secrets
echo ""
echo "正在创建 Docker secrets..."

# 删除已存在的 secrets（如果存在）
docker secret rm mimo_api_key 2>/dev/null || true
docker secret rm gitee_ai_key 2>/dev/null || true

# 创建新的 secrets
echo "$MIMO_API_KEY" | docker secret create mimo_api_key -
echo "$GITEE_AI_API_KEY" | docker secret create gitee_ai_key -

echo "✅ Docker secrets 创建成功"

# 启动服务
echo ""
echo "正在启动服务..."
docker-compose up -d

echo ""
echo "=================================="
echo "✅ 服务启动成功！"
echo "=================================="
echo ""
echo "访问地址："
echo "  后端 API: http://localhost:8000"
echo "  前端界面: http://localhost:3000"
echo "  API 文档: http://localhost:8000/docs"
echo ""
echo "查看日志："
echo "  docker-compose logs -f"
echo ""
echo "停止服务："
echo "  docker-compose down"
echo ""
echo "删除 secrets："
echo "  docker secret rm mimo_api_key gitee_ai_key"
echo "=================================="
