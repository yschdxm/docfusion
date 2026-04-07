#!/bin/bash
# Docker 镜像源配置脚本

echo "配置 Docker 国内镜像源..."

# 检查是否有 sudo 权限
if [ "$EUID" -ne 0 ]; then 
    echo "请使用 sudo 运行此脚本: sudo bash setup-docker.sh"
    exit 1
fi

# 创建配置目录
mkdir -p /etc/docker

# 写入镜像源配置
cat > /etc/docker/daemon.json << 'DOCKER_CONFIG'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
DOCKER_CONFIG

# 重启 Docker
systemctl daemon-reload
systemctl restart docker

echo "Docker 镜像源配置完成！"
echo "现在可以运行: sudo docker-compose up -d"
