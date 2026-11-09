# 第一课：跑通第一个后端接口

本课目标：理解一个 HTTP 请求如何进入 Python 程序，获得 JSON 响应。先建立后续 Agent 的运行基础。

## 1. 先确认解释器

在终端执行：

```powershell
conda activate Jun
Set-Location 'C:\Users\Administrator\Desktop\workspace\Agent\SalesAIbot'
python -c "import sys; print(sys.executable); print(sys.version)"
```

本机应看到 `C:\ProgramData\Anaconda3\envs\Jun\python.exe` 和 Python 3.10.19。之后尽量使用 `python -m ...`，让运行命令与当前解释器保持一致。

Jun 已具备本课依赖，无需重复安装。后续引入新依赖时再显式添加和验证。

PyCharm 中将项目解释器设为同一个 Jun 解释器，运行目录设为 `C:\Users\Administrator\Desktop\workspace\Agent\SalesAIbot`。IDE 的解释器和终端的解释器需要分别确认。

## 2. 这些文件各自做什么

| 文件 | 作用 |
|---|---|
| [app/__init__.py](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/app/__init__.py) | 标识 Python 应用包 |
| [app/config.py](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/app/config.py) | 读取本项目配置并检查类型和允许值 |
| [app/main.py](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/app/main.py) | 创建 FastAPI 应用，注册健康路由 |
| [requirements.txt](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/requirements.txt) | 声明运行依赖范围 |
| [.env.example](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/.env.example) | 可提交的配置模板 |
| [.gitignore](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/.gitignore) | 忽略本地凭据、IDE 文件和运行数据 |

`Settings` 是配置模型：`APP_ENV` 拼错时会启动失败，避免错误配置悄悄生效。

`HealthResponse` 是响应模型：约定返回字段及类型，同时生成接口文档。

`create_app()` 是创建应用的函数：后续测试可以传入测试配置，不必共用生产配置。

## 3. 启动服务

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

逐段理解：

- `python -m uvicorn`：使用当前 Jun 解释器启动 Uvicorn，它负责监听网络和运行应用。
- `app.main:app`：导入 `app` 包下的 `main` 模块，找到名叫 `app` 的 FastAPI 对象。
- `--reload`：开发时修改源码后自动重新加载。
- `--host 127.0.0.1`：本课仅在本机访问。
- `--port 8010`：监听端口，和老师示例区分。

保持这个终端运行，在浏览器访问 http://127.0.0.1:8010/health。

## 4. 看懂一次请求

```text
浏览器发送 GET /health
    → Uvicorn 接收 HTTP 请求
    → FastAPI 匹配 /health 路由
    → 执行 health()
    → 创建 HealthResponse
    → 校验并序列化为 JSON
    → 返回 HTTP 200
```

在 [app/main.py](C:/Users/Administrator/Desktop/workspace/Agent/SalesAIbot/app/main.py) 中，`@application.get(...)` 是路由装饰器：把请求方法、路径与下面的函数关联起来。

可以在另一个终端查看实际响应：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8010/health'
```

健康响应表示应用能够响应；它目前不检查模型、数据库或外部渠道。后续会区分进程健康和依赖就绪。

## 5. 使用接口文档

打开 http://127.0.0.1:8010/docs，展开 `GET /health`，点击 `Try it out`，再点 `Execute`。

观察请求地址、HTTP 200、返回 JSON 和响应 Schema。后续创建会话、提交消息和测试工具也会用到这个页面。

## 6. 一个配置小实验

先在原终端按 `Ctrl+C` 停止服务，再执行：

```powershell
$env:APP_NAME = 'SalesAIbot-Learning'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

再次访问 `/health`，观察 `app` 字段；访问 `/docs`，观察标题。这个实验只改变显示名称，不改变路由路径。

实验后按 `Ctrl+C` 停止服务，并恢复默认值：

```powershell
Remove-Item Env:APP_NAME
```

可选的 `.env` 文件用于保存本机配置，终端环境变量优先。第一课不需要模型密钥。

## 7. 常见问题

- `No module named uvicorn`：先检查 `sys.executable`，确认实际使用 Jun。
- 无法导入 `app`：确认当前工作目录是项目根目录，而不是其中的 `app` 文件夹。
- 8010 被占用：检查是否已有自己的开发服务；可以暂用 8011，并同步修改浏览器地址。不要停止不确定用途的进程。
- 浏览器无法访问：先看终端有没有启动成功；服务终端关闭后，接口也会停止。
- 访问 `/` 返回 404：本课只注册 `/health`，API 文档路径为 `/docs`。

## 8. 本课自查与下一课

- 我能独立激活 Jun、启动与停止服务。
- 我知道 Uvicorn 负责运行服务，FastAPI 负责路由和接口。
- 我能解释 `app.main:app`，并找到处理 `/health` 的函数。
- 我能区分配置模型与响应模型。
- 我知道目前还没有客户会话、数据库或模型调用。

下一课：实现创建会话、写入消息和读取历史，学习消息角色、持久化、幂等和版本冲突。
