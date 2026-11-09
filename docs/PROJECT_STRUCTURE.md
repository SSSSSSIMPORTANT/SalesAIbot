# 当前项目结构与阅读顺序

本次拆分覆盖已经实现的全部 HTTP 接口，接口地址与请求、响应结构保持不变。数据库模型和迁移没有改动。

```text
app/
├─ main.py                      # 创建 FastAPI，装配依赖，注册路由和错误处理
├─ version.py                   # 应用版本
├─ dependencies.py              # 每个应用实例的 AppRuntime，以及 get_runtime
├─ api/
│  ├─ router.py                 # 统一注册各领域路由
│  ├─ errors.py                 # 将服务错误转换为 HTTP 响应
│  ├─ health.py                 # 健康检查
│  ├─ customers.py              # 创建、查询客户
│  ├─ conversations.py          # 创建、查询会话
│  ├─ messages.py               # 消息预览、幂等补录、历史查询
│  ├─ memory.py                 # 事实确认、撤销、候选提取、跨会话召回
│  ├─ replies.py                # 回复预览
│  └─ suggestions.py           # 草稿保存、历史、失效检查、复制准备、复制报告
├─ schemas/
│  ├─ health.py
│  ├─ customers.py
│  ├─ conversations.py
│  ├─ messages.py
│  ├─ memory.py
│  ├─ replies.py
│  └─ suggestions.py           # 各领域请求和响应格式
├─ services/
│  ├─ errors.py                # 不依赖 FastAPI 的服务错误
│  ├─ replies.py               # 近期上下文、记忆快照、生成前后的版本检查
│  ├─ suggestions.py           # 草稿事务、复制前检查、复制报告幂等
│  ├─ memory_extraction.py     # 指定消息提取候选，校验来源与版本
│  ├─ turn_engine.py           # 有界工具/模型调度、资料校验、执行轨迹
│  ├─ messages.py              # 消息幂等与会话版本更新
│  ├─ memory.py                # 已确认事实的保存、更正、撤销
│  ├─ memory_recall.py         # 客户范围召回与事实差异识别
│  ├─ context.py               # 最近 16 条消息
│  ├─ reply_rendering.py       # 根据资料生成业务正文
│  └─ suggestion_validity.py   # 会话、记忆、知识变化检查
├─ database.py                  # ORM 模型、engine 和原 get_db 依赖
├─ llm.py                       # 模型网关、JSON/工具协议及模型数据结构
├─ knowledge.py                 # 产品目录读取与已发布资料查询
├─ tools.py                     # 工具定义、名称与参数校验、执行
├─ memory_candidates.py         # 记忆候选结构及允许的事实类别
└─ config.py                    # 配置加载与校验
```

## 如何追踪一次请求

以回复预览为例：

1. `api/replies.py` 接收请求，通过 `Depends(get_db)` 获取当前请求的数据库会话，通过 `get_runtime` 获取当前应用实例的引擎和工具。
2. `services/replies.py` 读取近期消息、召回客户事实，结束读取事务后调用引擎。
3. `services/turn_engine.py` 调用模型提出工具请求，执行工具，再把结果交给模型选择话题，校验来源后生成正文。
4. `services/replies.py` 再次检查会话和记忆是否变化，构造响应快照。

生成并保存草稿会从 `api/suggestions.py` 进入 `services/suggestions.py`，复用同一个回复预览服务。写入之前再次执行事务内检查，保存生成时的快照。

## 模块边界

- `schemas` 描述数据格式，不能导入 `main` 或 `api`。
- `api` 负责 HTTP 参数、依赖、状态码；复杂生成流程和事务在 `services`。
- `services` 不导入 `main` 或 `api`。`ServiceError` 由 `api/errors.py` 统一转换成原有的状态码和 `detail`。
- 简短的客户、会话查询仍在各自路由中，无需为每条 SQL 再增加一层。
- SQLAlchemy 数据库模型继续放在 `database.py`；网关协议、记忆领域数据结构保留原位置，避免本次 HTTP 模块拆分扩大到全部底层模块。

## 依赖为什么放在 AppRuntime

原来路由嵌套在 `create_app()` 中，直接使用外层的 gateway、repository、turn_engine 和 tool_executor。迁出后，这些对象放在 `application.state.runtime`，由 `get_runtime(request)` 按应用实例读取。

这样不同测试或应用实例可以注入不同模型与知识库，互不覆盖。`create_app(settings, model_gateway, knowledge_repository)` 的参数保持原样。

数据库仍使用 `app.database.get_db` 原函数。测试通过 `application.dependency_overrides[get_db]` 替换数据库，所有路由都能继续使用临时数据库。服务在每次操作时调用网关方法，应用创建后的测试 monkeypatch 仍有效。

## 启动和验证

在项目根目录运行：

```powershell
conda activate Jun
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8021
python -m pytest tests -q
```

这次重构不需要 Alembic 迁移，也不会自动调用真实模型。原 123 个测试继续验证业务行为，新增 3 个装配测试检查应用配置隔离、模型/知识库隔离以及 22 个接口无遗漏或重复注册。

建议阅读顺序：`main.py` → `dependencies.py` → `api/replies.py` → `services/replies.py` → `services/turn_engine.py`。随后阅读 `services/suggestions.py`，理解草稿保存与使用前检查的事务边界。
