# DocFusion

基于大语言模型的文档理解与多源数据融合系统

GitHub 仓库: https://github.com/yschdxm/docfusion.git

## 项目简介

DocFusion 是一个全栈 Web 应用，通过大语言模型实现文档的智能理解与多源数据融合。系统支持用户通过自然语言指令操作文档，自动提取非结构化文档信息，填写表格，并构建文档知识图谱。

### 核心功能

- **文档智能操作**: 通过自然语言指令对文档进行内容提取、格式转换、编辑修改，支持文档预览和搜索
- **信息自动提取**: 从 docx、xlsx、md、txt 等格式中提取实体、表格、自定义字段
- **智能表格填写**: 根据源文档自动填写模板表格，支持多源数据合并
- **知识图谱构建**: 自动抽取实体关系，支持可视化查询和跨文档关联发现
- **任务队列管理**: 异步任务队列控制并发处理，避免资源竞争和 API 过载
- **管理面板**: 用户管理、系统配置、文档管理等管理员功能
- **多语言支持**: 支持中文、英文、日文界面切换

## 技术栈

### 后端

| 技术 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 | 运行环境 |
| FastAPI | - | Web 框架 |
| SQLAlchemy | - | ORM |
| asyncio | - | 异步任务队列 |
| httpx | - | HTTP 客户端 |

### 前端

| 技术 | 版本 | 说明 |
|------|------|------|
| Node.js | 20 | 构建环境 |
| React | 18.3 | UI 框架 |
| TypeScript | - | 类型系统 |
| Vite | - | 构建工具 |
| Tailwind CSS | - | 样式框架 |
| Zustand | 4.5 | 状态管理 |
| React Router | 6.26 | 路由管理 |

### 数据库与存储

| 技术 | 用途 |
|------|------|
| PostgreSQL | 结构化数据存储 |
| Neo4j | 知识图谱存储 |
| Qdrant | 向量数据库 |
| ONLYOFFICE | 文档在线编辑 |

### AI 模型

| 模型 | 用途 |
|------|------|
| MiMO v2 Flash | 文档理解与生成 |
| DeepSeek V4 Flash | 文档理解与生成 |
| BGE-M3 | 文本嵌入 |
| BGE-Reranker-v2-M3 | 搜索重排 |

## Docker 镜像

### 自构建镜像

| 镜像名 | 基础镜像 | 说明 |
|--------|----------|------|
| docfusion-backend | python:3.11-slim | 后端服务 |
| docfusion-frontend | node:20-alpine / nginx:alpine | 前端服务 |

### 第三方镜像

| 镜像 | 版本 | 说明 |
|------|------|------|
| postgres | 17-alpine | PostgreSQL 数据库 |
| neo4j | 5 | Neo4j 图数据库 |
| qdrant/qdrant | latest | 向量数据库 |
| onlyoffice/documentserver | latest | 文档编辑服务 |

## 系统要求

- **Docker**: 20.10+
- **Docker Compose**: 2.0+

## 部署步骤

### 1. 克隆代码

```bash
git clone https://github.com/yschdxm/docfusion.git
cd docfusion
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下配置：

```env

# ============================================
# 数据库密码（请使用强密码）
# ============================================
POSTGRES_PASSWORD=your_strong_postgres_password
NEO4J_PASSWORD=your_strong_neo4j_password

# ============================================
# 应用配置
# ============================================
DEBUG=false
SECRET_KEY=your_random_secret_key_32_chars
ALLOWED_HOSTS=your-domain.com,localhost

# ============================================
# SSL 配置
# ============================================
SSL_VERIFY=true

# ============================================
# 日志级别（生产环境建议 INFO 或 WARNING）
# ============================================
LOG_LEVEL=INFO

# ============================================
# 管理员配置（可选）
# ============================================
# 首次启动时自动创建主管理员账号
# 如果不配置，系统会将第一个注册的用户设为主管理员
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=your_admin_password_here

# ============================================
# 模型配置说明
# ============================================
# 所有模型配置（LLM、嵌入、重排）通过管理中心在数据库中配置
# 支持任意 OpenAI 兼容的 API
# 首次启动后请访问 /admin 页面进行配置
```

### 3. 启动服务

```bash
docker-compose up -d
```

首次启动会自动构建镜像，约需 5-10 分钟。

### 4. 验证部署

```bash
# 检查服务状态（所有服务应为 Up 状态，postgres/neo4j 应为 healthy）
docker-compose ps

# 检查后端健康状态
curl http://localhost:8000/health

# 访问前端页面
curl -I http://localhost:3000
```

## 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:3000 | 用户界面 |
| 后端 API | http://localhost:8000 | API 服务 |
| API 文档 | http://localhost:8000/docs | Swagger UI |
| ONLYOFFICE | http://localhost:8088 | 文档编辑服务 |

## 用户功能

### 用户注册与登录

系统支持用户注册功能，可通过邮箱或手机号注册账号。注册开关可在管理面板中控制。

### 用户界面

- **仪表盘**: 系统概览和快捷入口
- **文档管理**: 上传、管理和组织文档
- **智能助手**: 通过自然语言指令操作文档，支持文档预览和搜索
- **知识图谱**: 可视化查看和查询文档知识图谱
- **工作日志**: 查看和管理工作记录
- **个人中心**: 个人信息管理

### 主题与语言

- **主题切换**: 支持系统跟随、商务蓝、夜间模式三种主题
- **多语言**: 支持中文、英文、日文界面切换

## 管理面板

管理员可通过 `/admin` 路径访问管理中心，功能包括：

- **用户管理**: 用户列表、角色分配、账号启用/禁用
- **系统配置**: 全局配置项管理
- **文档管理**: 系统文档统一管理
- **API 密钥管理**: 配置和管理 AI 模型 API 密钥
- **用量统计**: 查看系统资源使用情况

## 模型切换

系统支持自定义模型，并且可在模型之间切换。

### 前端切换

登录系统后，左下角 Engine 区域可通过下拉菜单切换模型。

### 管理面板切换

管理员可在管理面板中配置模型和 API 密钥。

## 常用运维命令

```bash
# 查看实时日志
docker-compose logs -f

# 查看单个服务日志
docker-compose logs -f backend

# 重启所有服务
docker-compose restart

# 重启单个服务
docker-compose restart backend

# 停止服务
docker-compose down

# 停止并删除数据卷（谨慎使用）
docker-compose down -v

# 更新部署
git pull
docker-compose up -d --build

# 查看资源使用
docker stats

# 进入容器调试
docker exec -it docfusion-backend /bin/bash
```

## 故障排除

### 服务启动失败

```bash
# 查看错误日志
docker-compose logs backend

# 检查环境变量配置
docker-compose config
```

### 数据库连接失败

```bash
# 检查数据库服务状态
docker-compose ps
# postgres 和 neo4j 状态应为 healthy

# 手动测试数据库连接
docker exec -it docfusion-postgres psql -U docfusion -d docfusion
```

### 前端无法访问

```bash
# 检查端口占用
lsof -i :3000

# 检查 nginx 配置
docker exec -it docfusion-frontend nginx -t
```

### AI 模型调用失败

1. 检查 API Key 是否正确配置
2. 检查服务器网络是否能访问模型服务
3. 查看后端日志获取详细错误信息：
   ```bash
   docker-compose logs backend | grep -i "llm\|model\|api"
   ```

## 项目结构

```
docfusion/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/v1/            # API 路由
│   │   │   └── endpoints/     # API 端点
│   │   │       ├── admin.py   # 管理面板接口
│   │   │       ├── agent.py   # 智能助手接口
│   │   │       ├── auth.py    # 认证接口
│   │   │       └── documents.py # 文档接口
│   │   ├── core/              # 核心配置
│   │   ├── models/            # 数据库模型
│   │   ├── schemas/           # Pydantic 模式
│   │   ├── services/          # 业务逻辑服务
│   │   │   ├── task_queue.py  # 任务队列管理
│   │   │   └── config_service.py # 配置服务
│   │   ├── agent/             # AI Agent 系统
│   │   └── main.py            # 应用入口
│   ├── requirements.txt       # Python 依赖
│   └── Dockerfile
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── components/        # UI 组件
│   │   │   └── layout/        # 布局组件（支持响应式）
│   │   ├── pages/             # 页面
│   │   │   ├── AdminCenter.tsx # 管理中心
│   │   │   ├── Login.tsx      # 登录页
│   │   │   └── Register.tsx   # 注册页
│   │   ├── hooks/             # 自定义 Hooks
│   │   ├── services/          # API 服务
│   │   └── stores/            # 状态管理
│   ├── package.json           # Node.js 依赖
│   └── Dockerfile
├── docker-compose.yml          # 生产环境部署配置
├── .env.example                # 环境变量模板
└── README.md                   # 本文档
```

## 许可证

私有项目，未经授权禁止使用。
