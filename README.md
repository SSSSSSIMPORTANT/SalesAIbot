# SalesAIbot

从零搭建销售 Agent 的学习项目。当前已实现客户与会话、消息、千问模型、受控工具调用、客户记忆、回复草稿、失效检查和复制报告。

模块划分与阅读顺序见 [项目结构说明](docs/PROJECT_STRUCTURE.md)。

## 运行服务

本机已有 conda 环境 `Jun`（Python 3.10.19），所需依赖已安装。打开 PowerShell：

```powershell
conda activate Jun
Set-Location 'C:\Users\Administrator\Desktop\workspace\Agent\SalesAIbot'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8021
```

本项目统一使用 8021 端口，便于和老师示例区分。终端出现 `Uvicorn running on http://127.0.0.1:8021` 后，打开：

- 健康接口：http://127.0.0.1:8021/health
- 可交互接口文档：http://127.0.0.1:8021/docs
- 接口规范：http://127.0.0.1:8021/openapi.json

健康接口应返回：

```json
{
  "status": "ok",
  "app": "SalesAIbot",
  "environment": "development",
  "version": "0.1.0"
}
```

在运行服务的终端按 `Ctrl+C` 停止。Uvicorn 默认在终端输出启动、关闭和请求日志。

如果终端没有配置 `conda`，可在 Anaconda Prompt 中激活 Jun，或直接运行已确认的解释器：

```powershell
& 'C:\ProgramData\Anaconda3\envs\Jun\python.exe' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8021
```

## 配置与依赖

默认使用 mock 模式，可离线开发和测试。需要修改时，在项目根目录将 `.env.example` 复制为 `.env`，再编辑 `APP_NAME` 或 `APP_ENV`。终端环境变量优先于 `.env`；`APP_ENV` 只接受 `development`、`test`、`production`。

新电脑或新环境才需要安装运行依赖：

```powershell
python -m pip install -r 'C:\Users\Administrator\Desktop\workspace\Agent\SalesAIbot\requirements.txt'
```

mock 模式不需要模型密钥；live 模式需要配置千问连接信息。`.env`、客户数据和本地数据库不进入 Git。

## 学习顺序

1. 阅读 [MVP 范围](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/docs/MVP_SCOPE.md)，理解先实现的业务。
2. 跟着 [第一课](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/docs/LESSON_01.md) 启动服务、调用接口，并解释请求经过哪些代码。
3. 阅读 [项目结构说明](docs/PROJECT_STRUCTURE.md)，从应用装配追踪到路由、服务和回合引擎。

当前 `/health` 只证明应用能响应请求。模型、知识与记忆的调用结果通过业务接口验证；身份认证和人工工作台仍待后续实现。
