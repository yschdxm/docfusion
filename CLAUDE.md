# CLAUDE.md

## 项目概述

**项目名称：** 基于大语言模型的文档理解与多源数据融合系统

**项目类型：** 全栈Web应用

**核心技术栈：**
- 后端：Python FastAPI + Celery + Redis
- 前端：React 18 + TypeScript + Vite + Tailwind CSS
- 数据库：PostgreSQL + MongoDB + Neo4j
- AI模型：MiMO v2 Flash (通过API调用)
- 部署：Docker Compose

## 项目结构

```
code3/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/v1/            # API路由
│   │   ├── core/              # 核心配置
│   │   ├── models/            # 数据库模型
│   │   ├── schemas/           # Pydantic模式
│   │   ├── services/          # 业务逻辑服务
│   │   ├── db/                # 数据库连接
│   │   └── main.py            # 应用入口
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── components/        # UI组件
│   │   ├── pages/             # 页面
│   │   ├── hooks/             # 自定义Hooks
│   │   ├── services/          # API服务
│   │   └── stores/            # 状态管理
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── AGENTS.md
```

## 核心模块说明

### 1. 文档智能操作交互模块

功能：用户通过自然语言指令操作文档

支持操作：
- 内容提取与查询
- 格式转换 (docx ↔ md, xlsx ↔ csv)
- 内容编辑与修改
- 排版格式调整

关键文件：
- backend/app/services/document_agent.py - 智能Agent核心
- backend/app/api/v1/endpoints/documents.py - API端点
- frontend/src/pages/DocumentOperation.tsx - 前端页面

### 2. 非结构化文档信息提取模块

功能：从非结构化文档中自动提取关键信息

支持格式：docx, xlsx, md, txt

提取类型：
- 实体识别 (人名、地名、机构、日期、数值)
- 表格数据提取
- 自定义字段提取

### 3. 表格自定义数据填写模块

功能：根据源文档自动填写模板表格

使用场景：
- 根据Word报告填写Excel汇总表
- 根据Excel数据填写Word模板
- 多源数据合并填写

### 4. 知识图谱模块

功能：构建文档知识图谱，支持语义查询和关联发现

核心能力：
- 自动实体关系抽取
- 知识图谱可视化
- 基于图谱的问答
- 跨文档数据关联发现

## 环境变量配置

POSTGRES_URL=postgresql://docfusion:docfusion123@postgres:5432/docfusion
MONGODB_URL=mongodb://mongo:27017/docfusion
NEO4J_URL=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j123
REDIS_URL=redis://redis:6379/0
MIMO_API_KEY=sk-cnp5q8ys4bj0xmked6o0913fyq6jzjt1cs5o5ucxik57a49q
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2-flash
APP_SECRET_KEY=docfusion-secret-key-2024

## 启动命令

开发环境：

```bash
# 后端
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```

Docker部署：

```bash
docker-compose up -d
```

## Lint命令

```bash
# 后端
cd backend
ruff check app/

# 前端
cd frontend
npm run lint
```
