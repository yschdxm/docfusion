# DocFusion

基于大语言模型的文档理解与多源数据融合系统。项目提供**文档管理、智能问答、信息抽取、表格填充、知识图谱、LangChain RAG 扩展、邮箱 Agent 集成**等能力，支持开发环境运行与 Docker Compose 一键部署。

---

## 目录

- [项目简介](#项目简介)
- [核心能力](#核心能力)
- [技术架构](#技术架构)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
  - [方式一：Docker Compose 部署](#方式一docker-compose-部署)
  - [方式二：本地开发启动](#方式二本地开发启动)
- [环境变量说明](#环境变量说明)
- [LangChain 集成说明](#langchain-集成说明)
- [邮箱 Agent 集成说明](#邮箱-agent-集成说明)
- [主要接口概览](#主要接口概览)
- [前端页面说明](#前端页面说明)
- [开发建议](#开发建议)
- [常见问题](#常见问题)

---

## 项目简介

DocFusion 是一个面向文档理解与多源数据融合场景的全栈 Web 应用，后端基于 **FastAPI**，前端基于 **React 18 + TypeScript + Vite + Tailwind CSS**，并结合 **PostgreSQL、Neo4j、Qdrant、OnlyOffice** 与多种大模型能力，构建统一的文档处理与知识增强平台。

项目当前可用于以下典型场景：

- 多格式文档上传、管理与预览
- 文档内容抽取、结构化处理与知识沉淀
- 基于向量检索与重排的 RAG 问答
- 表格模板自动填充
- 文档知识图谱构建与语义关联
- 基于腾讯 Agent Mail / `agently-cli` 的邮件收发与附件导入
- 结合 LangChain 的低侵入式链路编排扩展

---

## 核心能力

### 1. 文档管理与智能操作
- 支持文档上传、分类、状态管理
- 支持文档智能操作页面
- 支持自然语言驱动的文档问答与处理
- 提供流式 Agent 接口能力

### 2. 非结构化文档信息提取
- 支持 `docx`、`xlsx`、`md`、`txt` 等格式
- 支持实体识别、表格抽取、字段提取
- 源文档导入后可进入抽取任务队列

### 3. 表格自动填充
- 根据已有文档或抽取结果，对模板表格执行自动填充
- 适用于报告整理、汇总表生成、多源数据对齐等场景

### 4. 知识图谱
- 支持文档实体关系抽取与图谱构建
- 基于 Neo4j 存储知识关系
- 支持语义查询与跨文档关联发现

### 5. LangChain RAG 扩展
- 已集成 `langchain`、`langchain-core`、`langchain-community`、`langchain-openai`
- 提供对现有 RAG 检索栈的 LangChain 封装
- 保持现有项目检索服务不变，仅在上层新增 retriever / prompt / chain 编排能力

### 6. 邮箱 Agent / 邮件管理
- 已集成腾讯 Agent Mail 能力
- 后端通过 `agently-cli` 执行邮件收发、读取、附件下载
- 前端提供邮件管理页面
- 支持将邮件附件直接导入文档系统，并自动触发后续抽取流程

---

## 技术架构

### 后端
- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Neo4j
- Qdrant
- LangChain
- Celery（依赖已存在）
- OnlyOffice 集成

### 前端
- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- Zustand
- TanStack React Query
- Axios
- vis-network

### AI / 检索能力
- MiMO / DeepSeek 大模型
- Gitee AI 嵌入与重排模型
- 向量检索 + 重排
- LangChain ChatModel / Retriever / Chain 适配

---

## 项目结构

```text
docfusion/
├── backend/                         # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/                  # API 路由
│   │   ├── agent/                   # Agent 运行时与工具
│   │   ├── core/                    # 配置、日志、依赖
│   │   ├── db/                      # PostgreSQL / Neo4j 连接
│   │   ├── models/                  # 数据模型
│   │   ├── schemas/                 # Pydantic 模型
│   │   └── services/                # 业务服务
│   │       ├── langchain/           # LangChain 适配层
│   │       ├── agently_mail_service.py
│   │       └── vector_store_service.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                        # React 前端
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── pages/
│   │   ├── services/
│   │   └── stores/
│   ├── package.json
│   └── Dockerfile
├── onlyoffice/                      # OnlyOffice 配置
├── docker-compose.yml               # 标准部署编排
├── docker-compose.dev.yml           # 开发部署编排
├── .env.example                     # 环境变量模板
└── README.md
```

---

## 快速开始

## 方式一：Docker Compose 部署

### 1）准备环境变量

复制模板文件：

```bash
cp .env.example .env
```

根据你的实际环境补充以下核心变量：

- `MIMO_API_KEY`
- `GITEE_AI_API_KEY`
- `POSTGRES_PASSWORD`
- `NEO4J_PASSWORD`
- `SECRET_KEY`

如果你需要启用 LangChain 中的 DeepSeek 模型调用，还需要配置：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`

如果你需要启用邮箱 Agent，还需要配置：

- `AGENTLY_CLI_BIN`
- `SMTP_SERVER`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`

> 注意：邮箱 Agent 的核心依赖是 `agently-cli` 的本机可执行与授权状态，SMTP 变量主要用于普通邮件发送相关场景。

### 2）启动服务

```bash
docker-compose up -d --build
```

### 3）访问地址

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`
- OnlyOffice：`http://localhost:8088`

### 4）容器组成

`docker-compose.yml` 默认包含以下服务：

- `backend`
- `frontend`
- `postgres`
- `neo4j`
- `qdrant`
- `onlyoffice`

---

## 方式二：本地开发启动

> 推荐先确保 PostgreSQL、Neo4j、Qdrant 等依赖服务可用，或者通过 Docker 单独启动这些基础设施。

### 启动后端

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

后端启动后可访问：

- `GET /`：返回 API 名称与版本
- `GET /health`：健康检查

### 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认开发地址通常为：

- 前端开发服务器：`http://localhost:5173`

---

## 环境变量说明

根目录提供了 `.env.example` 作为模板，下面是主要变量分类说明。

### 1. 大模型与嵌入配置

```env
MIMO_API_KEY=
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2-flash

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash

GITEE_AI_API_KEY=
GITEE_AI_BASE_URL=https://ai.gitee.com/v1
EMBEDDING_MODEL=bge-m3
RERANK_MODEL=bge-reranker-v2-m3
```

### 2. 检索限流配置

```env
LLM_RPM=100
LLM_TPM=10000000
```

### 3. SSL 与安全配置

```env
SSL_VERIFY=true
SSL_VERIFY_MIMO=true
SSL_VERIFY_GITEE_AI=true

DEBUG=false
SECRET_KEY=your_secret_key_here
ALLOWED_HOSTS=*
```

后端内置支持 `ALLOWED_HOSTS` 白名单与 CIDR 网段校验，以降低非法 Host 头访问风险。

### 4. 数据库配置

```env
POSTGRES_PASSWORD=your_strong_postgres_password
NEO4J_PASSWORD=your_strong_neo4j_password
UPLOAD_DIR=./uploads
MAX_FILE_SIZE=52428800
```

### 5. SMTP 邮件配置

```env
SMTP_SERVER=smtp.qq.com
SMTP_PORT=587
SMTP_USER=你的邮箱@qq.com
SMTP_PASSWORD=你的授权码
```

### 6. Agent Mail / agently-cli 配置

```env
AGENTLY_CLI_BIN=agently-cli
AGENTLY_MAIL_TIMEOUT_SECONDS=120
```

`.env.example` 中还保留了以下命令模板变量说明：

```env
AGENTLY_MAIL_LIST_COMMAND=
AGENTLY_MAIL_DETAIL_COMMAND=
AGENTLY_MAIL_SEND_COMMAND=
AGENTLY_MAIL_ATTACHMENT_COMMAND=
```

不过从当前后端实现看，核心列表、详情、发送、确认发送、附件下载命令已在 `backend/app/services/agently_mail_service.py` 中直接组装执行，主要依赖：

- `agently-cli +me`
- `agently-cli message +list --dir inbox --limit <n>`
- `agently-cli message +read --id <message_id>`
- `agently-cli message +send ...`
- `agently-cli attachment +download ...`

如果在 Windows 本机开发环境中 `agently-cli` 不在 PATH，可将 `AGENTLY_CLI_BIN` 配置为完整路径，例如：

```env
AGENTLY_CLI_BIN=C:\Users\你的用户名\AppData\Roaming\npm\agently-cli.cmd
```

---

## LangChain 集成说明

项目已经显式引入以下依赖：

- `langchain==0.3.27`
- `langchain-core==0.3.74`
- `langchain-community==0.3.27`
- `langchain-openai==0.2.14`

相关实现目录：

```text
backend/app/services/langchain/
├── __init__.py
├── prompts.py
├── retriever.py
├── llm_adapter.py
└── chains.py
```

### 设计思路

当前 LangChain 集成是**低侵入式适配**，不会直接替换现有业务链路，而是对既有能力做包装：

1. **Retriever 层**  
   `DocFusionRetriever` 对现有 `rag_service` 做异步封装，保留以下既有检索栈不变：
   - embedding_service
   - vector_store_service
   - rerank_service
   - 自定义 metadata 处理

2. **Model 层**  
   `llm_adapter.py` 中的 `get_langchain_chat_model()` 复用项目已有环境变量配置，支持：
   - `deepseek`
   - `mimo`

3. **Chain 层**  
   `chains.py` 中提供 `answer_with_langchain_rag()`，实现：
   - 检索相关文档
   - 拼接上下文
   - 使用 LangChain Prompt + ChatModel 调用
   - 返回答案、上下文数量、来源元数据

### 典型用途

- 为后续 Agent / Chain 实验提供标准入口
- 在不破坏既有 RAG 系统的情况下，引入 LangChain 生态
- 为多轮对话、工具调用、结构化输出扩展做铺垫

### 示例说明

`answer_with_langchain_rag()` 的核心能力包括：

- 输入问题 `question`
- 指定模型提供方 `provider`
- 控制 `top_k` 与 `rerank_top_n`
- 返回：
  - `question`
  - `answer`
  - `provider`
  - `context_count`
  - `sources`

这意味着你可以在现有文档知识系统之上，继续扩展：

- LangChain Agent
- 结构化输出链
- 组合式 Prompt 模板
- 多工具路由链

---

## 邮箱 Agent 集成说明

项目已包含完整的**邮箱 Agent 能力**，后端通过 `agently-cli` 与腾讯 Agent Mail 交互，前端提供独立的邮件管理页面。

### 前端入口

路由位置：

- `/email-management`

相关页面文件：

- `frontend/src/pages/EmailManagement.tsx`

页面能力包括：

- 查看 Agent Mail 授权状态
- 刷新收件箱
- 查看邮件详情
- 发送邮件
- 两阶段确认发送
- 从“文档管理”中选择文件作为附件
- 将邮件附件导入系统文档库

### 后端 API

路由前缀：

```text
/api/v1/agent-mail
```

当前主要接口：

- `GET /status`  
  检查邮箱 Agent 是否可用、是否已授权

- `GET /messages?limit=20`  
  获取收件箱邮件列表

- `GET /messages/{message_id}`  
  获取单封邮件详情

- `POST /send`  
  发起邮件发送，可能返回 `confirmation_token`

- `POST /send/confirm`  
  使用确认 token 完成最终发送

- `POST /attachments/import`  
  下载并导入邮件附件到系统文档库

### 两阶段发送机制

根据当前实现，`agently-cli message +send` 可能是一个两阶段过程：

1. 第一次请求发送  
   返回确认摘要与 `confirmation_token`
2. 用户确认后再次提交  
   调用 `/send/confirm` 真正发送邮件

这部分逻辑已在前端 `EmailManagement.tsx` 中实现。

### 附件导入能力

`agently_mail_service.py` 支持：

1. 下载指定邮件附件
2. 过滤支持导入的文件类型：
   - `docx`
   - `xlsx`
   - `md`
   - `txt`
3. 将附件复制到系统上传目录
4. 写入文档记录
5. 若分类为 `source`，自动创建抽取任务
6. 触发后续文档抽取队列

这意味着邮件附件可以直接作为新的知识源进入系统，完成从“邮件 -> 文档 -> 抽取 -> 检索”的闭环。

### 授权与安装建议

在后端运行环境中，先确认：

```bash
agently-cli +me
```

如果未授权，通常需要先完成登录或 OAuth 流程。若后端报错提示找不到 `agently-cli`，请：

1. 安装 `agently-cli`
2. 完成授权
3. 将 `AGENTLY_CLI_BIN` 配置为正确路径

---

## 主要接口概览

根据 `backend/app/api/v1/api.py`，当前 API 路由包含：

- `/api/v1/auth`
- `/api/v1/documents`
- `/api/v1/knowledge`
- `/api/v1/agent`
- `/api/v1/agent`（流式能力）
- `/api/v1/conversations`
- `/api/v1/table-fill`
- `/api/v1/agent-mail`

你可以基于 FastAPI 自动文档进一步查看详细参数与响应结构。

---

## 前端页面说明

根据当前路由配置，主要页面包括：

- `/`：仪表盘
- `/documents`：文档管理
- `/document-operation`：文档智能操作
- `/work-log`：工作日志
- `/email-management`：邮件管理
- `/profile`：个人中心
- `/login`：登录
- `/register`：注册

---

## 开发建议

### 后端代码规范
建议执行：

```bash
cd backend
ruff check app/
```

### 前端代码规范

```bash
cd frontend
npm run lint
```

### 推荐开发顺序

1. 配置 `.env`
2. 启动 PostgreSQL / Neo4j / Qdrant
3. 启动后端
4. 启动前端
5. 验证 `/health`
6. 登录系统后测试：
   - 文档上传
   - 抽取任务
   - 邮件管理
   - LangChain RAG 扩展接口或测试脚本

---

## 常见问题

### 1. 后端启动成功，但邮件页面提示未授权
说明 `agently-cli` 未安装、未登录，或 `AGENTLY_CLI_BIN` 路径错误。请先在后端运行环境中执行：

```bash
agently-cli +me
```

### 2. 邮件可以看到，但发送时失败
可能原因：

- 未完成 Agent Mail 授权
- 两阶段发送未进行确认
- 附件路径不存在
- Windows 下 `agently-cli.cmd` 未正确配置

### 3. LangChain 已安装，但无法调用模型
请检查：

- `DEEPSEEK_API_KEY` 是否配置
- `MIMO_API_KEY` 是否配置
- `BASE_URL` 与模型名是否正确
- 网络 / SSL 配置是否正常

### 4. RAG 检索效果不稳定
请优先检查：

- Qdrant 是否正常运行
- 嵌入模型是否正确配置
- 重排模型是否可用
- 文档是否已成功抽取、入库

### 5. OnlyOffice 无法访问
请检查：

- `onlyoffice` 容器是否正常启动
- `8088` 端口是否被占用
- `ONLYOFFICE_*` 相关环境变量是否正确

---

## 说明

本 README 基于当前仓库代码结构整理，重点补充了以下内容：

- **LangChain 集成**
- **邮箱 Agent / 腾讯 Agent Mail**
- **Docker 与本地启动方式**
- **环境变量说明**
- **模块结构与接口入口**

如果你后续希望，我还可以继续帮你补充：
- API 文档章节
- 系统截图
- 时序图 / 架构图
- 开发路线图
- 贡献指南 / License