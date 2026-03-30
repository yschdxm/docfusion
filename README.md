# 基于大语言模型的文档理解与多源数据融合系统

## 项目简介

本项目是一个全栈 Web 应用，旨在通过大语言模型（LLM）实现文档的智能理解与多源数据融合。系统支持用户通过自然语言指令操作文档，自动提取非结构化文档信息，填写表格，并构建文档知识图谱。

## 核心功能

### 1. 文档智能操作交互模块
用户可以通过自然语言指令对文档进行操作：
- **内容提取与查询**：从文档中提取特定内容
- **格式转换**：支持 docx ↔ md, xlsx ↔ csv 等格式转换
- **内容编辑与修改**：直接修改文档内容
- **排版格式调整**：调整文档的排版和格式

### 2. 非结构化文档信息提取模块
从非结构化文档中自动提取关键信息：
- **支持格式**：docx, xlsx, md, txt
- **提取类型**：
  - 实体识别（人名、地名、机构、日期、数值）
  - 表格数据提取
  - 自定义字段提取

### 3. 表格自定义数据填写模块
根据源文档自动填写模板表格：
- **使用场景**：
  - 根据 Word 报告填写 Excel 汇总表
  - 根据 Excel 数据填写 Word 模板
  - 多源数据合并填写

### 4. 知识图谱模块
构建文档知识图谱，支持语义查询和关联发现：
- **核心能力**：
  - 自动实体关系抽取
  - 知识图谱可视化
  - 基于图谱的问答
  - 跨文档数据关联发现

## 技术栈

- **后端**：Python FastAPI + Celery + Redis
- **前端**：React 18 + TypeScript + Vite + Tailwind CSS
- **数据库**：PostgreSQL + MongoDB + Neo4j
- **AI 模型**：MiMO v2 Flash（通过 API 调用）
- **部署**：Docker Compose

## 项目结构

```
code3/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/v1/            # API 路由
│   │   ├── core/              # 核心配置
│   │   ├── models/            # 数据库模型
│   │   ├── schemas/           # Pydantic 模式
│   │   ├── services/          # 业务逻辑服务
│   │   ├── db/                # 数据库连接
│   │   └── main.py            # 应用入口
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── components/        # UI 组件
│   │   ├── pages/             # 页面
│   │   ├── hooks/             # 自定义 Hooks
│   │   ├── services/          # API 服务
│   │   └── stores/            # 状态管理
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

## 环境变量配置

### 开发环境

开发环境下，使用 `.env` 文件管理环境变量。复制模板文件并填入真实的 API key：

```bash
cp .env.example .env
```

`.env` 文件配置示例：

```env
# MiMO API 配置
MIMO_API_KEY=your_mimo_api_key_here
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2-flash

# Gitee AI API 配置
GITEE_AI_API_KEY=your_gitee_ai_key_here
GITEE_AI_BASE_URL=https://ai.gitee.com/v1
EMBEDDING_MODEL=bge-m3
RERANK_MODEL=bge-reranker-v2-m3

# 应用配置
DEBUG=true
SECRET_KEY=your_secret_key_here

# 数据库配置
POSTGRES_URL=postgresql://docfusion:docfusion123@localhost:5432/docfusion
MONGODB_URL=mongodb://localhost:27017/docfusion
NEO4J_URL=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
REDIS_URL=redis://localhost:6379/0

# Celery 配置
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

**注意**：`.env` 文件包含敏感信息，不要提交到版本控制系统。

### Docker 完整部署（生产环境，尚未验证）

生产环境下，使用 Docker secrets 管理敏感信息，确保安全性。

**敏感信息配置**：
- API 密钥和数据库密码存储在 Docker secrets 中
- `.env` 文件仅用于创建 secrets，不直接挂载到容器
- 通过 `/run/secrets/` 路径访问 secrets

**环境变量文件路径**：
- `MIMO_API_KEY_FILE=/run/secrets/mimo_api_key`
- `GITEE_AI_API_KEY_FILE=/run/secrets/gitee_ai_key`

完整配置参考 `docker-compose.yml` 文件中的 environment 和 secrets 部分。

## 快速开始

### 前置步骤

1. **复制环境变量模板**：
   ```bash
   cp .env.example .env
   ```

2. **编辑 `.env` 文件**，填入真实的 API key：
   - `MIMO_API_KEY` - MIMO API 密钥
   - `GITEE_AI_API_KEY` - Gitee AI API 密钥

### 方式一：开发环境启动（推荐）

开发环境下，我们使用 Python 虚拟环境运行后端服务，npm 运行前端服务，同时使用 Docker 启动数据库服务。

#### 使用启动脚本

```bash
# 启动数据库服务
./start-dev.sh
```

#### 手动启动

```bash
# 1. 启动数据库服务
docker-compose -f docker-compose.dev.yml up -d

# 2. 启动后端服务
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. 启动前端服务
cd frontend
npm install
npm run dev
```

### 方式二：完整 Docker 部署（生产环境，尚未验证）

使用 Docker secrets 管理敏感信息，确保安全性。

#### 使用启动脚本

```bash
# 启动所有服务（自动创建 Docker secrets）
./start-with-secrets.sh
```

#### 手动启动

1. **创建 Docker secrets**：
   ```bash
   # 从 .env 文件读取 API key 并创建 secrets
   MIMO_API_KEY=$(grep "^MIMO_API_KEY=" .env | cut -d'=' -f2-)
   GITEE_AI_API_KEY=$(grep "^GITEE_AI_API_KEY=" .env | cut -d'=' -f2-)

   echo "$MIMO_API_KEY" | docker secret create mimo_api_key -
   echo "$GITEE_AI_API_KEY" | docker secret create gitee_ai_key -
   ```

2. **启动服务**：
   ```bash
   docker-compose up -d
   ```

3. **查看服务状态**：
   ```bash
   docker-compose ps
   ```

4. **查看日志**：
   ```bash
   docker-compose logs -f
   ```

5. **停止服务**：
   ```bash
   docker-compose down
   ```

6. **删除 secrets**（可选）：
   ```bash
   docker secret rm mimo_api_key gitee_ai_key
   ```

## 开发规范

### 代码检查

#### 后端（Python）

```bash
cd backend
ruff check app/
```

#### 前端（TypeScript/JavaScript）

```bash
cd frontend
npm run lint
```

## API 文档

启动后端服务后，可以通过以下地址访问 API 文档：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc