# AI Playwright Tester

一个使用 AI 多轮观察、决策并执行 Playwright 浏览器测试的轻量平台。

## 核心流程

1. 前端提交目标 URL、测试目标和浏览器模式。
2. Playwright 启动 Chromium 并打开目标页面。
3. 观察器提取当前 URL、标题、ARIA 可访问性树、可交互元素和截图。
4. Agent 根据真实页面状态选择一个结构化动作。
5. 后端执行白名单动作，再把新页面状态或执行错误交给 Agent。
6. 循环执行，直到 Agent 完成、主动失败、连续动作失败或达到步数上限。
7. 后端保存实际执行步骤、运行记录、最终截图和 Playwright Trace。

Agent 不再返回任意 Python 代码。它只能选择导航、点击、输入、按键、勾选、
选择、页面断言、完成或失败等结构化动作。接口中的 `generated_code` 是后端根据
实际成功或尝试过的动作还原出的 Playwright 代码，方便阅读和复用。

## 后端结构

```text
app/
├── api/
│   ├── dependencies.py       # FastAPI 依赖装配
│   ├── router.py             # API 总路由
│   └── routes/
│       ├── health.py         # 健康检查
│       └── runs.py           # 测试运行 API
├── core/
│   ├── config.py             # 环境变量与统一配置
│   ├── exceptions.py         # 业务异常
│   └── logging.py            # 日志初始化
├── repositories/
│   └── run_repository.py     # 文件型运行记录仓库
├── schemas/
│   └── run.py                # 请求、响应和领域数据模型
├── services/
│   ├── agent_service.py      # 多轮模型决策与模拟 Agent
│   ├── page_observer.py      # DOM、ARIA、元素和截图观察
│   ├── browser_action_service.py # 白名单浏览器动作
│   ├── playwright_service.py # Agent 循环、浏览器和产物采集
│   └── run_service.py        # 一次测试任务的完整编排
└── main.py                   # FastAPI 应用创建与异常处理
```

`public/` 保存当前简单前端，`runs/` 保存每次测试的运行记录和产物，`tests/` 保存后端单元测试。

## 安装和启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path $env:TEMP "ai-playwright-browsers")
python -m playwright install chromium
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000，API 文档位于 http://127.0.0.1:8000/docs。

## 模型配置

默认 `MOCK_MODE=true`，不会调用真实模型。模拟 Agent 会执行两步循环：验证当前
URL，然后结束测试，用于检查观察、动作、截图和 Trace 链路。

使用真实模型时修改 `.env`：

```dotenv
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_JSON_RESPONSE_MODE=true
MOCK_MODE=false
```

`OPENAI_BASE_URL` 可以替换为兼容 OpenAI Chat Completions 的服务地址。如果服务不支持 `response_format`，设置 `OPENAI_JSON_RESPONSE_MODE=false`。

模型需要支持图片输入才能同时利用页面截图。对于不支持视觉输入的模型，将
`AGENT_INCLUDE_SCREENSHOT=false`，Agent 仍会使用 ARIA 树和可交互元素列表。

## Agent 循环配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_MAX_STEPS` | `12` | 单次测试最多决策步数 |
| `AGENT_MAX_CONSECUTIVE_FAILURES` | `3` | 连续动作失败终止阈值 |
| `AGENT_ACTION_TIMEOUT_MS` | `10000` | 单个 Playwright 动作超时 |
| `AGENT_OBSERVATION_CHARS` | `12000` | 发送给模型的 ARIA 内容上限 |
| `AGENT_DOM_CHARS` | `12000` | 发送给模型的清理后 DOM 内容上限 |
| `AGENT_OBSERVATION_DELAY_MS` | `250` | 动作后等待页面稳定的时间 |
| `AGENT_INCLUDE_SCREENSHOT` | `true` | 是否向模型发送当前页面截图 |
| `AGENT_HISTORY_LIMIT` | `8` | 每轮携带的最近动作数量 |
| `TEST_TIMEOUT_SECONDS` | `180` | 整个多轮测试的总超时 |

## API

| 方法 | 地址 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 查看服务和 Agent 模式 |
| POST | `/api/run` | 原前端兼容入口 |
| POST | `/api/runs` | 创建并同步执行测试 |
| GET | `/api/runs?limit=20` | 查询最近运行记录 |
| GET | `/api/runs/{run_id}` | 查询运行详情 |
| GET | `/api/runs/{run_id}/screenshot.png` | 查看截图 |
| GET | `/api/runs/{run_id}/trace.zip` | 下载 Trace |
| GET | `/api/runs/{run_id}/result.json` | 下载完整运行记录 |

每次运行的数据保存在 `runs/{run_id}/`。当前使用文件仓库，不需要数据库。

## 测试

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

## 当前边界

- API 仍然同步等待浏览器测试结束，没有任务队列。
- 运行历史使用本地 JSON 文件，不适合多实例共享。
- Agent 只执行结构化白名单动作，不执行模型返回的任意代码。
- 页面内容和截图会发送给配置的大模型服务，敏感测试环境应使用可信模型端点。
- 当前未对目标 URL 做内外网隔离，公开部署前必须增加 SSRF 和网络访问策略。
- 默认最多同时执行两个浏览器任务，可通过 `MAX_CONCURRENT_RUNS` 调整。
- 若需要部署到公网，应进一步增加登录鉴权、目标 URL 网络隔离和容器沙箱。
