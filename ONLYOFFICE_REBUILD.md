# ONLYOFFICE 生产镜像打包指南

开发完成后，将修改后的 ONLYOFFICE SDK 打包为可部署的生产镜像。

## 官方资源

- [build_tools](https://github.com/ONLYOFFICE/build_tools) - 官方构建工具
- [Docker-DocumentServer](https://github.com/ONLYOFFICE/Docker-DocumentServer) - 官方 Docker 镜像构建仓库
- [DocumentServer](https://github.com/ONLYOFFICE/DocumentServer) - 源码仓库

## 前提条件

- 已克隆 SDK 源码到 `onlyoffice-sdk/` 目录
- 已完成开发和测试
- 已安装 Python 3、Docker

## 方式一：使用官方 build_tools（推荐）

这是官方推荐的构建方式，适用于完整的 Document Server 构建。

### 1. 克隆 build_tools

```bash
git clone https://github.com/ONLYOFFICE/build_tools.git
cd build_tools
```

### 2. 复制修改后的 SDK 源码

将修改后的源码替换 build_tools 中的对应目录：

```bash
# 复制修改后的 sdkjs
cp -r /path/to/docfusion/onlyoffice-sdk/sdkjs/* ./sdkjs/

# 复制修改后的 web-apps
cp -r /path/to/docfusion/onlyoffice-sdk/web-apps/* ./web-apps/

# 复制修改后的 server
cp -r /path/to/docfusion/onlyoffice-sdk/server/* ./server/
```

### 3. 构建 Document Server

```bash
cd tools/linux
python3 ./automate.py server
```

构建完成后，产物在 `./out/linux_64/onlyoffice/documentserver/` 目录。

### 4. 使用 Docker 构建镜像

```bash
cd build_tools

# 创建输出目录
mkdir -p out

# 构建 Docker 镜像
docker build --tag onlyoffice-documentserver-custom .

# 或者使用官方 Docker-DocumentServer 仓库
```

## 方式二：基于官方镜像构建

适用于只需要替换前端资源的场景。

### 1. 构建 SDK

```bash
# 构建 sdkjs
cd onlyoffice-sdk/sdkjs
python build.py
cd ../..

# 构建 web-apps
cd onlyoffice-sdk/web-apps/build
npm install
npx grunt deploy
cd ../../..
```

### 2. 创建 Dockerfile

```dockerfile
FROM onlyoffice/documentserver:latest

# 复制构建好的前端资源
COPY onlyoffice-sdk/sdkjs/deploy/sdkjs/ /var/www/onlyoffice/documentserver/sdkjs/
COPY onlyoffice-sdk/web-apps/deploy/web-apps/ /var/www/onlyoffice/documentserver/web-apps/

# 重新生成字体缓存（如果修改了字体相关代码）
RUN rm -rf /var/www/onlyoffice/documentserver/fonts && \
    mkdir -p /var/www/onlyoffice/documentserver/fonts && \
    LD_LIBRARY_PATH=/var/www/onlyoffice/documentserver/server/FileConverter/bin \
    /var/www/onlyoffice/documentserver/server/tools/allfontsgen \
    --input="/var/www/onlyoffice/documentserver/core-fonts" \
    --allfonts-web="/var/www/onlyoffice/documentserver/sdkjs/common/AllFonts.js" \
    --allfonts="/var/www/onlyoffice/documentserver/server/FileConverter/bin/AllFonts.js" \
    --images="/var/www/onlyoffice/documentserver/sdkjs/common/Images" \
    --selection="/var/www/onlyoffice/documentserver/server/FileConverter/bin/font_selection.bin" \
    --output-web='fonts' \
    --use-system="true"
```

### 3. 打包镜像

```bash
docker build -t docfusion-onlyoffice:latest .
```

## 方式三：使用官方 Docker-DocumentServer 仓库

适用于需要完整控制镜像构建过程的场景。

### 1. 克隆仓库

```bash
git clone https://github.com/ONLYOFFICE/Docker-DocumentServer.git
cd Docker-DocumentServer
```

### 2. 替换 SDK 源码

根据仓库中的 `.gitmodules` 配置，替换对应的子模块。

### 3. 构建镜像

```bash
# 使用官方 Makefile
make

# 或使用 docker-compose
docker-compose build
```

## 部署到生产环境

### 推送到镜像仓库

```bash
# 标记镜像
docker tag docfusion-onlyoffice:latest your-registry.com/docfusion-onlyoffice:latest

# 推送镜像
docker push your-registry.com/docfusion-onlyoffice:latest
```

### 修改 docker-compose.yml

```yaml
services:
  onlyoffice:
    # 替换为自定义镜像
    image: your-registry.com/docfusion-onlyoffice:latest
    # 或使用本地镜像
    # image: docfusion-onlyoffice:latest
```

### 启动服务

```bash
docker-compose up -d
```

## 验证

```bash
# 检查服务状态
docker-compose ps onlyoffice

# 健康检查
curl http://localhost:8088/healthcheck

# 查看日志
docker-compose logs onlyoffice
```

## 相关链接

- [ONLYOFFICE 官方构建文档](https://helpcenter.onlyoffice.com/docs/installation/docs-community-compile.aspx)
- [build_tools 使用说明](https://github.com/ONLYOFFICE/build_tools#how-do-i-use-it-on-linux-)
- [Docker-DocumentServer 说明](https://github.com/ONLYOFFICE/Docker-DocumentServer)
- [ONLYOFFICE 开发者文档](https://api.onlyoffice.com/)
