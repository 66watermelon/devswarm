# DevSwarm 算法推演平台 — 项目技术文档

> **版本：** 2.2.1
> **定位：** Multi-Agent 协同算法推演与个性化学习平台
> **架构：** Clean Architecture + CQRS + GraphRAG
> **更新日期：** 2026-06-04

---

## 一、技术栈

| 层级 | 技术 | 说明 |
|---|---|---|
| **Web 框架** | FastAPI (Python 3.11) | 全异步，lifespan 资源管理 |
| **前端** | Vue 2.6 + Element UI + ECharts 5 | CDN 模式，零构建工具 |
| **AI 编排** | LangGraph + LangChain | 多 Agent DAG 有向图执行 |
| **LLM 引擎** | DeepSeek (API 兼容 OpenAI) | v4-pro / v4-flash，分角色调温 |
| **关系数据库** | MySQL 8.0 + SQLAlchemy 2.0 | 双引擎：同步 pymysql + 异步 aiomysql |
| **长期记忆** | PostgreSQL 16 + psycopg | LangGraph AsyncPostgresSaver，高并发连接池 |
| **图数据库** | Neo4j 5.x | 异步驱动，认知图谱存储与多跳雷达查询 |
| **缓存 / 消息** | Redis 7.x | JWT 滑动窗口 + 分布式锁 + Pub/Sub 流式广播 |
| **代码沙箱** | Docker (python:3.11-slim) | 断网 / 无特权 / 资源受限 / 零残留 |
| **安全** | bcrypt + JWT (HS256) | 24h 过期 + Redis jti 吊销 |
| **Markdown** | marked.js + KaTeX | 客户端渲染，支持 LaTeX 公式 |
| **代码高亮** | highlight.js | 支持 Python 语法 |

---

## 二、项目拓扑

```
┌──────────────────────────────────────────────────────┐
│                   前端 (Vue 2 SPA)                      │
│   index.html (工作台)  │  login.html  │  profile.html   │
└─────────┬────────────────────────────────────────────┘
          │ HTTP SSE (POST /stream) + REST API
          ▼
┌──────────────────────────────────────────────────────┐
│                  FastAPI (main.py)                     │
│  ┌──────────┬──────────┬──────────┬──────────────┐   │
│  │ /auth    │ /chat    │ /graph   │ /users       │   │
│  │ 注册登录  │ CQRS流式 │ Neo4j图谱 │ 用户信息      │   │
│  └──────────┴────┬─────┴──────────┴──────────────┘   │
│                  │                                     │
│  ┌───────────────▼──────────────────────────────┐    │
│  │          LangGraph 执行图 (main_graph.py)      │    │
│  │  intent_recognizer → analyst → dev → qa → tutor │   │
│  │                   ↘ chat_agent                 │    │
│  └───────────────┬──────────────────────────────┘    │
│                  │                                     │
│  ┌───────────────▼──────────────────────────────┐    │
│  │      LangGraph Checkpoint (PostgreSQL)         │    │
│  │   AsyncPostgresSaver + psycopg 异步连接池       │    │
│  └──────────────────────────────────────────────┘    │
└────────────────────┬─────────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌─────────┐   ┌──────────┐   ┌──────────┐
│  MySQL  │   │  Neo4j   │   │  Redis   │
│ 用户/会话│   │ 认知图谱  │   │ 锁/PubSub │
└─────────┘   └──────────┘   └──────────┘
     ▲
     │   ┌──────────────┐
     └───│ PostgreSQL   │
         │ Checkpoint   │
         └──────────────┘
```

---

## 三、后端架构

### 3.1 目录结构（V5 Clean Architecture）

```
devswarm_core/
├── main.py                  # FastAPI 入口，lifespan 四引擎资源管理
├── main_graph.py            # LangGraph 执行图定义 + Checkpointer 编译
├── services/                # 🆕 领域服务层（与 api/core 平级）
│   ├── stream_service.py    #   CQRS Worker：跑图 + Redis Pub/Sub 广播
│   └── memory_service.py    #   GraphRAG：记忆吸收流水线
├── core/
│   ├── config.py            # pydantic-settings 全局配置（含 PG_CHECKPOINT_URL）
│   ├── constants.py         # 🆕 全局常量：EOF_MARKER, SKIP_NODES, NODE_DISPLAY_MAP
│   ├── security.py          # bcrypt 密码哈希 + JWT 签发/校验
│   ├── engine/
│   │   ├── state.py         # DevState TypedDict（图全局状态，14 字段）
│   │   ├── llm_factory.py   # LLM 连接池（7 个角色实例）
│   │   ├── sandbox.py       # Docker 安全沙箱引擎
│   │   ├── memory_extractor.py  # 认知记忆 LLM 抽取器
│   │   └── exceptions.py    # 统一异常体系
│   ├── nodes/               # 6 个 Agent 节点
│   │   ├── intent_recognizer_node.py   # 入口：意图识别 + 主题分类
│   │   ├── analyst_node.py            # 算法分析 + 多跳前置雷达
│   │   ├── developer_node.py          # 代码生成 + 正则提取
│   │   ├── qa_node.py                 # 沙箱判题 + 重试门禁
│   │   ├── tutor_node.py              # 题解输出 + 认知图谱注入
│   │   └── chat_agent_node.py         # 答疑解惑 + 上下文感知
│   ├── prompts/             # 各 Agent 系统提示词（6 个）
│   ├── tools/               # LangChain 工具（文件读写、沙箱执行）
│   └── utils/
│       ├── ha_utils.py      # 指数退避重试（4 次，2s→16s）
│       ├── memory_utils.py  # 上下文窗口修剪（4 种策略）
│       ├── sse_utils.py     # 🆕 SSE 协议格式化
│       ├── message_utils.py # 🆕 节点内容提取 + 消息清洗
│       └── graph_memory_injector.py  # 认知图谱潜意识注入
├── db/
│   ├── database.py          # SQLAlchemy 双引擎（sync + async）+ Redis 鉴权客户端
│   ├── postgres_client.py   # 🆕 PostgreSQL Checkpoint 连接池（psycopg）
│   ├── redis_client.py      # 🆕 流式推演专用 Redis（端口 6380，db 1）
│   ├── neo4j_client.py      # Neo4j 异步单例连接池
│   ├── graph_writer.py      # 认知图谱写入（Cypher 事务）
│   └── graph_reader.py      # 认知图谱读取 + Markdown 格式化 + 多跳雷达
├── models/
│   ├── user.py              # User ORM（id, username, hashed_password, created_at）
│   └── thread.py            # Thread ORM（id UUID, user_id FK, title, created_at, updated_at）
├── schemas/
│   ├── user.py / chat.py    # Pydantic 请求/响应模型
│   ├── graph_memory.py      # 认知图谱 DTO（ConceptNode, SkillAssessment, UserState）
│   ├── knowledge_dict.py    # AlgorithmTopic Literal（90+ 算法节点）
│   └── algorithm_data.py    # 全量算法认知图谱基建数据（110 节点 + 118 边）
├── api/
│   ├── deps.py              # JWT + Redis 滑动窗口鉴权依赖（全异步）
│   └── routes/
│       ├── auth_routes.py   # POST /register, /login, /logout
│       ├── chat_routes.py   # 🆕 精简至 147 行，纯路由端点
│       ├── graph_routes.py  # Neo4j 图谱 CRUD
│       └── user_routes.py   # GET /users/{id}
└── workspace/               # Agent 文件读写工作区（Docker bind-mount 源）
```

### 3.2 LangGraph 执行图（三模式统一拓扑）

图拓扑本身不变——三种模式共用同一张 DAG，差异通过 `mode` 字段在节点内部动态切换行为。

```
                        START
                          │
                   ┌──────▼──────┐
                   │  intent_    │  三分类：solve / diagnose / chat
                   │  recognizer │  + user_memory_context 读取
                   └──────┬──────┘
                          │
              task?               chat?
                │                    │
         ┌──────▼──────┐    ┌──────▼──────┐
         │   analyst   │    │  chat_agent │  知识答疑 + 图谱雷达
         │ 策略+用例     │    │              │
         └──────┬──────┘    └──────┬──────┘
                │                  │
   solve?       │       diagnose?  │
     ┌──────────┘           ┌──────┘
     ▼                      ▼
┌──────────┐          ┌──────────┐
│developer │          │    qa    │  diagnose 直连 QA
└────┬─────┘         └────┬─────┘
     │                    │
 tool_calls?         tool_calls?       fail<3?
  │      │            │      │           │
 YES    NO           YES    NO     ┌─────┘
  │      │            │      │     ▼
  ▼      ▼            ▼      ▼  ┌──────────┐
┌────┐ ┌───┐      ┌────┐  ┌───┐│developer │  修复代码
│dev │ │ qa│      │qa  │  │判 │└────┬─────┘
│tool│ └─┬─┘      │tool│  │定 │     │
└──┬─┘   │        └──┬─┘  │门 │◄────┘
   └─────┘           └────┐禁 │
                          └─┬─┬─┘
                    solve   │  diagnose
                      │     │     │
                      ▼     │     ▼
                   ┌──────┐│  ┌──────────┐
                   │tutor ││  │chat_agent│  诊断反馈
                   └──┬───┘│  └────┬─────┘
                      │    │       │
                      ▼    │       ▼
                     END ◄─┘      END
```

**三种模式的路径总结：**

```
solve:    intent_recognizer → analyst → developer → qa ⇄ dev_tools/qa_tools
          → (pass) tutor → END
          → (fail<3) 回到 developer
          → (fail≥3 熔断) tutor → END

diagnose: intent_recognizer → analyst → qa（直连）
          → (pass) chat_agent → END
          → (fail<3) developer → qa → ...
          → (fail≥3 熔断) chat_agent → END

chat:     intent_recognizer → chat_agent → END
```

**6 个 Agent 节点三模式行为矩阵：**

| 节点 | solve 模式 | diagnose 模式 | chat 模式 |
|---|---|---|---|
| `intent_recognizer` | 读 Neo4j→`user_memory_context`，判 mode=solve | 读 Neo4j，有 user_code→强制 mode=diagnose | 判 user_intent=chat |
| `analyst` | **唯一决策器**。根据 user_memory 产出完整 strategy（算法+复杂度+用户适配）+ edge_cases | 根据 user_memory 产出代码审查指引 strategy（可用/避开的知识点）+ edge_cases | 不参与 |
| `developer` | **纯执行器**。读 strategy+edge_cases→从零写代码。不读 user_memory | 读 strategy+user_code+QA反馈→修复代码。不读 user_memory | 不参与 |
| `qa` | 测 developer 生成的代码 | 测 user_code，侧重逻辑错误 > 性能 | 不参与 |
| `tutor` | 读全部 state→Markdown 题解+认知注入 | 不参与（diagnose 出口走 chat_agent） | 不参与 |
| `chat_agent` | 不参与 | **diagnose 出口**：按 QA 结果给反馈（通过→恭喜+分析，失败→指出错误+建议） | **chat 入口**：答疑+图谱雷达+认知注入 |

**核心设计原则：analyst 是"用户知识翻译官"的唯一责任点。** developer 永不直接读 user_memory_context——solve 下通过 strategy 间接获取，diagnose 下同样通过 strategy 获取。接口契约统一，模式差异封装在 analyst 内部。

### 3.2.1 三种模式逐节点详细数据流

#### 模式 1：solve（求解模式）—— 用户要求解新题

**触发条件：** 用户输入纯文字题目，不粘贴代码。intent_recognizer 判定 `mode="solve"`。

**完整路径：** `intent_recognizer → analyst → developer → qa ⇄ qa_tools → (pass) tutor → END ｜ (fail) 回到 developer`

---

**节点 1：intent_recognizer**

| 维度 | 内容 |
|---|---|
| **读 state** | `messages[-1]`（最新一条用户消息）、`user_id`、`user_code`（空） |
| **外部调用** | `GraphReader.fetch_user_knowledge_profile(user_id)` → Neo4j 查询用户掌握/薄弱的全部知识点 |
| **LLM 调用** | `llm_intent`（flash v4, temp=0.0），结构化提取 `IntentAndTopicExtraction` |
| **写 state** | `user_intent="task"`, `mode="solve"`, `current_topic="数组"`, `user_memory_context="{用户知识档案...}"` |
| **不写入** | messages（不污染对话历史） |

---

**节点 2：analyst**

| 维度 | 内容 |
|---|---|
| **读 state** | `problem_description`（题目原文）、`user_memory_context`（用户知识档案）、`mode`（solve）、`current_topic`、`user_id`、`messages`（修剪后 3 轮白名单历史） |
| **外部调用** | `GraphReader.check_prerequisites(user_id, current_topic)` → 多跳雷达：缺失知识点 + 内部拓扑依赖边 |
| **提示词追块** | solve 模式无条件块。若前置缺失 → `prereq_warning`（"放弃推演，输出补课大纲"）。若用户档案非空 → `memory_block`（"用户掌握X薄弱Y"） |
| **LLM 调用** | `llm_analyst`（pro v4, temp=0.3, thinking=ON） |
| **写 state** | `messages: [AIMessage(name="analyst")]`, `algorithm_strategy="双指针解法 O(n)，避免递归（用户 DP 薄弱）..."`, `edge_cases="assert two_sum([], 0)==-1..."` |
| **role** | 教学决策者——"这道题应该怎么教、用什么方法、规避什么" |

→ **路由：** `route_after_analysis` → `mode=="solve"` → `"developer"`

---

**节点 3：developer**

| 维度 | 内容 |
|---|---|
| **读 state** | `strategy`（analyst 的策略）、`edge_cases`（测试用例）、`problem_description`（题目）、`mode`（solve）、`user_code`（空）、`messages`（修剪后：system + 最新 QA 报错） |
| **提示词追块** | solve 模式 → "【求解模式 —— 从零编写代码】"。不注入 user_memory_context（strategy 已含） |
| **LLM 调用** | `get_developer_llm_with_tools()`（pro v4, temp=0.2, thinking=OFF, 绑定文件读写工具） |
| **工具调用** | `write_workspace_file("solution.py", code)` → 将代码写入工作区 |
| **写 state** | `messages: [AIMessage(name="developer")]`, `generated_code="def two_sum(nums, target):\n    ..."` |
| **role** | 纯执行器——"分析师说用双指针，我就用双指针写" |

→ **路由：** `route_after_developer` → 无 tool_calls → `"qa"`

---

**节点 4：qa**

| 维度 | 内容 |
|---|---|
| **读 state** | `generated_code`（developer 的代码）、`edge_cases`（analyst 的测试用例）、`problem_description`、`mode`（solve） |
| **提示词追块** | 注入题目 + 边界用例。solve 模式无特殊块 |
| **LLM 调用** | `get_qa_llm_with_tools()`（flash v4, temp=0.1, thinking=OFF, 绑定沙箱工具） |
| **工具调用** | `read_workspace_file("solution.py")` → `write_workspace_file("test_solution.py")` → `run_sandbox_test`（Docker 沙箱执行） |
| **写 state** | `messages: [AIMessage(name="qa")]`, `execution_feedback=""`（通过）或 `"IndexError..."`（失败）, `retry_count`（通过=0，失败=累加） |
| **role** | 判题官——"代码能不能跑通所有测试" |

→ **路由：** `route_after_qa` →
  - `pass` → `mode=="solve"` → `"tutor"`
  - `fail, retry<3` → `"developer"`（回到节点 3 修复）
  - `fail, retry≥3` → 熔断 → `"tutor"`

---

**节点 5：tutor**

| 维度 | 内容 |
|---|---|
| **读 state** | `problem_description`、`algorithm_strategy`、`edge_cases`、`generated_code`、`execution_feedback`、`user_id`、`messages`（修剪后 3 轮白名单历史） |
| **外部调用** | `get_graph_memory_prompt(user_id)` → Neo4j 读取用户行为画像（红温指数、bad smells、薄弱点Top10）→ 包装为潜意识提示块 |
| **LLM 调用** | `llm_tutor`（flash v4, temp=0.5, thinking=ON） |
| **写 state** | `messages: [AIMessage(name="tutor")]`, `final_explanation="# 【算法题解】两数之和\n..."` |
| **role** | 知识输出者——"汇总全过程，写一篇学生能看懂的题解" |

→ **路由：** `tutor → END`

---

#### 模式 2：diagnose（诊断模式）—— 用户带代码调试

**触发条件：** 用户在"粘贴代码"区粘贴了代码。intent_recognizer 检测 `state["user_code"]` 非空 → 强制 `mode="diagnose"`。

**完整路径：** `intent_recognizer → analyst → qa（直连，跳过 developer）→ (pass) chat_agent → END ｜ (fail) developer → qa → ...`

> 注：首轮 diagnose 跳过 developer——先让 QA 跑用户原始代码看报什么错。只有 QA 测试失败后，developer 才介入修复。

---

**节点 1：intent_recognizer**

| 维度 | 内容 |
|---|---|
| **读 state** | `messages[-1]`、`user_id`、`user_code`（非空！） |
| **外部调用** | `GraphReader.fetch_user_knowledge_profile(user_id)` |
| **LLM 调用** | `llm_intent` 结构化提取 |
| **写 state** | `user_intent="task"`, `mode="diagnose"`（user_code 非空兜底强制）, `current_topic="数组"`, `user_memory_context="..."` |
| **不写入** | messages |

---

**节点 2：analyst**

| 维度 | 内容 |
|---|---|
| **读 state** | `problem_description`、`user_memory_context`、`mode`（diagnose）、`current_topic`、`user_id`、`messages` |
| **外部调用** | `GraphReader.check_prerequisites(user_id, current_topic)` |
| **提示词追块** | diagnose 模式 → "不要写完整算法策略。根据用户知识档案，输出代码审查指引到 strategy 字段：可用/避开的知识点、编码风格。提取边界测试用例到 edge_cases。" |
| **LLM 调用** | `llm_analyst` |
| **写 state** | `messages: [AIMessage(name="analyst")]`, `algorithm_strategy="用户薄弱于边界处理→修复后加 if not nums: return []。保留原双指针结构，不用哈希表改写。"`, `edge_cases="assert user_func([],0)==-1..."` |
| **role** | 与 solve 相同——翻译用户知识为可执行指引，但内容从"算法策略"变为"审查指引" |

→ **路由：** `route_after_analysis` → `mode=="diagnose"` → `"qa"`（**直连 QA，跳过 developer**）

---

**节点 3：qa（首轮）**

| 维度 | 内容 |
|---|---|
| **读 state** | `user_code`（非空！）、`mode`（diagnose）、`edge_cases`（analyst 的测试用例）、`problem_description`、`generated_code`（首轮为空） |
| **代码选择** | `code_to_test = generated_code or user_code` → 首轮 generated_code 为空 → 用 user_code |
| **提示词追块** | diagnose 模式 → "🔧 诊断模式：请将此代码写入 solution.py 并测试"。追加判题侧重——"优先关注逻辑错误和边界漏洞，非性能问题" |
| **文件操作** | LLM 工具调用：`write_workspace_file("solution.py", user_code)` → `write_workspace_file("test_solution.py")` → `run_sandbox_test` |
| **写 state** | `execution_feedback=""`（通过）或 `"IndexError..."`（失败）, `retry_count` |

→ **路由：** `route_after_qa` →
  - `pass` → `mode=="diagnose"` → `"chat_agent"`
  - `fail, retry<3` → `"developer"`（首次进入修复）
  - `fail, retry≥3` → 熔断 → `"chat_agent"`

---

**节点 4：developer（仅在 QA 失败后介入）**

| 维度 | 内容 |
|---|---|
| **读 state** | `strategy`（analyst 的审查指引）、`execution_feedback`（QA 报错）、`edge_cases`、`mode`（diagnose）、`retry_count` |
| **代码上下文** | `retry_count == 0` 时注入 `user_code`（首次修复，参考原始代码）；`retry_count > 0` 时注入 `generated_code`（重试修复，基于上次修改继续迭代） |
| **提示词追块** | diagnose 模式 → "【诊断模式 —— 修复已有代码】"。prompt 注入当前轮次的代码上下文 + QA 报错 |
| **LLM 工具调用** | `write_workspace_file("solution.py", fixed_code)` → 修复后的代码写入物理文件 |
| **state 提取** | 正则从 LLM 回复中提取代码块 → 存入 `generated_code` |
| **写 state** | `messages: [AIMessage(name="developer")]`, `generated_code`（修复后的代码） |
| **role** | 代码医生——首次修读原始代码，后续迭代只看自己的上一版修复 |

---

**节点 5：chat_agent（diagnose 出口）**

| 维度 | 内容 |
|---|---|
| **读 state** | `mode`（diagnose）、`execution_feedback`（空=通过 ｜ 非空=失败）、`user_code`、`strategy`（analyst 审查指引）、`generated_code`（如果 developer 修过） |
| **外部调用** | `get_graph_memory_prompt(user_id)`（行为画像：红温指数、bad smells） |
| **提示词追块** | diagnose 出口 → 按 QA 结果分两种：通过时 → "恭喜用户，分析复杂度，温和优化建议"；失败/熔断时 → "指出关键错误行，给出修复思路但不直接重写，保持鼓励" |
| **LLM 调用** | `llm_chat`（flash v4, temp=0.5, thinking=OFF） |
| **写 state** | `messages: [AIMessage(name="chat_agent")]` |
| **role** | 诊断反馈者——"把 QA 的冷冰冰报错翻译成导师风格的对话" |

→ **路由：** `chat_agent → END`

---

#### 模式 3：chat（聊天模式）—— 用户纯文字提问

**触发条件：** 用户输入中没有代码，且 intent_recognizer 判定 `user_intent="chat"`。

**完整路径：** `intent_recognizer → chat_agent → END`

---

**节点 1：intent_recognizer**

| 维度 | 内容 |
|---|---|
| **读 state** | `messages[-1]`、`user_id` |
| **外部调用** | `GraphReader.fetch_user_knowledge_profile(user_id)` |
| **写 state** | `user_intent="chat"`, `current_topic="动态规划 (DP)"`, `user_memory_context="..."` |

→ **路由：** `route_after_intent` → `user_intent=="chat"` → `"chat_agent"`

---

**节点 2：chat_agent**

| 维度 | 内容 |
|---|---|
| **读 state** | `user_id`、`current_topic`、`generated_code`（如果有）、`user_code`、`problem_description`、`algorithm_strategy`、`execution_feedback`（如果有——前一题的状态可能恢复过来） |
| **外部调用** | `get_graph_memory_prompt(user_id)` → 从 Neo4j 取行为画像 → 包装为 `<User_Cognitive_Profile>` 潜意识提示块。`GraphReader.check_prerequisites(user_id, current_topic)` → 多跳雷达检测前置缺失 |
| **内部处理** | `_build_context(state)` → 拼装当前工作区代码、题目、分析摘要 |
| **提示词追块** | 基础提示词（导师人设）+ 行为画像 + 前置雷达拦截警告（若有）+ 系统内部状态 + 当前上下文 |
| **LLM 调用** | `llm_chat`（flash v4, temp=0.5, thinking=OFF） |
| **写 state** | `messages: [AIMessage(name="chat_agent")]` |
| **role** | 全知导师——"结合用户的认知水平和当前工作区状态，回答任何提问" |

→ **路由：** `chat_agent → END`

---

#### 三种模式下 state 字段的读写总结

| state 字段 | solve | diagnose | chat |
|---|---|---|---|
| `user_code` | 空 | ✅ 前端传入 → qa 测 → developer 读 | 空 |
| `user_intent` | intent 写 `"task"` | intent 写 `"task"` | intent 写 `"chat"` |
| `mode` | intent 写 `"solve"` | intent 写 `"diagnose"` | intent 写无所谓（不进入流水线） |
| `user_memory_context` | intent 读 Neo4j 写入 → analyst 读 | intent 读 Neo4j 写入 → analyst 读 | intent 读 Neo4j 写入 |
| `current_topic` | intent 写 → analyst 用于雷达 | intent 写 → analyst 用于雷达 | intent 写 → chat_agent 用于雷达 |
| `algorithm_strategy` | analyst 写（完整策略）→ developer 读 → tutor 读 | analyst 写（审查指引）→ developer 读 → chat_agent 读 | 不参与 |
| `edge_cases` | analyst 写 → qa 读 → developer 读 | analyst 写 → qa 读 → developer 读 | 不参与 |
| `generated_code` | developer 写 → qa 读 → tutor 读 | developer 写 → qa 读 → chat_agent 读 | chat_agent 读（如果有） |
| `execution_feedback` | qa 写（空=通过）→ developer 读 → tutor 读 | qa 写 → developer 读 → chat_agent 读 | chat_agent 读（如果有） |
| `retry_count` | qa 写 → route_after_qa 读 | qa 写 → route_after_qa 读 | 不使用 |
| `final_explanation` | tutor 写 | 不使用 | 不使用 |

### 3.2.2 代码存储与流转机制

代码有两种存在形式：**state 字段**（LangGraph 管理的结构化数据）和**文件系统**（`workspace/solution.py`，工具写入）。

```
                    ┌─ state["generated_code"] ──┐
                    │  (正则从LLM回复中提取)       │
                    │                             │
developer ─────────┤                             ├──→ qa 读取测试
                    │                             │
                    └─ write_workspace_file       │
                       ("solution.py") ───────────┘
                       (LLM 工具调用写入文件)
```

**solve 模式：**
1. developer 的 prompt 看到 `strategy` + `edge_cases` → LLM 产出代码
2. developer 的 LLM 调用 `write_workspace_file("solution.py", code)` → 代码写入物理文件
3. developer 用正则从 LLM 回复中提取代码块 → 存入 `state["generated_code"]`
4. qa 的 LLM 调用 `read_workspace_file("solution.py")` → 从物理文件读代码 → 写测试 → `run_sandbox_test`

**diagnose 模式：**
1. `user_code` 从前端传入 → 存入 `state["user_code"]`（原始代码，全程不变）
2. **首轮 qa**：`code_to_test = user_code`（generated_code 为空）→ 通过 prompt 指示 LLM 写入 `solution.py` → 沙箱执行 → 报错
3. **developer**：prompt 中看到 `user_code`（原始代码）+ `strategy`（审查指引）+ `execution_feedback`（QA 报错）→ LLM 修复 → `write_workspace_file("solution.py", fixed_code)` → 正则提取存入 `generated_code`
4. **后续 qa**：`code_to_test = generated_code`（非空时优先）→ 通过 prompt 指示 LLM 写入 `solution.py` → 沙箱执行 → 通过/再修

> **关键修复（v2.2.1）：**
> 1. **QA 代码选择：** qa 在 diagnose 模式下根据 `generated_code` 是否为空决定测哪个代码。`generated_code` 非空（developer 已修复）优先用它，为空（首轮）才用 `user_code`。避免 QA 重测时用原始代码覆盖 developer 的修复。
> 2. **Developer 重试：** diagnose 模式下 developer 首次被调用时看到 `user_code`（原始代码），重试时（`retry_count > 0`）看到自己上次的 `generated_code`。避免原始代码干扰迭代修复。
> 3. **续轮 user_code 传递：** `run_graph_worker` 在续轮（`has_history=True`）时检查 `user_code` 非空则写入增量 state，确保同一 thread 内后续轮次也能触发 diagnose 模式。

### 3.3 DevState 状态结构

```python
class DevState(TypedDict):
    # ==========================================
    # 1. 核心对话流（LangGraph 内建 add_messages reducer）
    # ==========================================
    messages: Annotated[list[AnyMessage], add_messages]

    # ==========================================
    # 2. 输入层 —— 用户提供
    # ==========================================
    problem_description: str    # 算法题目描述
    user_code: str              # 诊断模式：用户已有代码

    # ==========================================
    # 3. 分析层 —— Analyst 产出
    # ==========================================
    algorithm_strategy: str     # 算法思路 + 复杂度分析
    edge_cases: str             # 边界测试用例

    # ==========================================
    # 4. 执行层 —— Developer 产出、QA 反馈
    # ==========================================
    generated_code: str         # Developer 生成的 Python 代码
    execution_feedback: str     # QA 沙箱反馈（空=通过）

    # ==========================================
    # 5. 输出层 —— Tutor 产出
    # ==========================================
    final_explanation: str      # 最终 Markdown 题解

    # ==========================================
    # 6. 控制层
    # ==========================================
    retry_count: int            # QA 打回重试计数器（上限 3）
    mode: str                   # "solve" | "diagnose"
    user_intent: str            # "task" | "chat"
    user_id: int                # 当前用户 ID
    current_topic: Optional[str]   # 当前算法主题（用于雷达检测）
```

### 3.4 记忆策略：双层架构

```
┌─────────────────────────────────────────────┐
│     Layer 1: Checkpoint (PostgreSQL)         │
│  AsyncPostgresSaver + psycopg 连接池         │
│  全量持久化：messages + 所有 state 字段       │
│  首轮：完整初始化 → 续轮：增量追加            │
└──────────────┬──────────────────────────────┘
               │ 恢复到 DevState
               ▼
┌─────────────────────────────────────────────┐
│     Layer 2: Context Window Trimmer           │
│  4 种策略，按 Agent 角色差异化过滤            │
│                                              │
│  ┌────────────────┬──────────────────────┐  │
│  │ 对话型 (3轮白名单)│ 执行型 (极简防雪球)   │  │
│  │ analyst        │ developer            │  │
│  │ tutor          │ qa                   │  │
│  │ chat_agent     │                      │  │
│  ├────────────────┼──────────────────────┤  │
│  │ 分类型          │                      │  │
│  │ intent_recognizer│                    │  │
│  │ (仅最新1条用户)  │                      │  │
│  └────────────────┴──────────────────────┘  │
└─────────────────────────────────────────────┘
```

**消息身份标签体系：**

| 节点 | `response.name` | 被谁看到 |
|---|---|---|
| `analyst` | `"analyst"` | analyst / tutor / chat_agent |
| `developer` | `"developer"` | 仅 qa（trim_for_qa 倒序查找） |
| `qa` | `"qa"` | 仅 developer（trim_for_developer 倒序查找） |
| `tutor` | `"tutor"` | analyst / tutor / chat_agent |
| `chat_agent` | `"chat_agent"` | analyst / tutor / chat_agent |

---

## 四、核心功能

### 4.1 智能体协同推演（三模式架构）

平台通过 `intent_recognizer` 将用户输入自动分类为三种模式，同一张 LangGraph DAG 通过 `mode` 字段驱动节点内部的行为切换：

| 模式 | 触发条件 | 完整路径 | 出口 Agent | 用户得到什么 |
|---|---|---|---|---|
| **solve** | 用户要求解新题，无代码 | analyst→dev→qa→tutor | tutor | 完整 Markdown 题解 |
| **diagnose** | 用户粘贴代码，要求调试 | analyst→qa→dev⇄qa→chat_agent | chat_agent | 沙箱反馈 + 修复对话 |
| **chat** | 用户纯文字提问/闲聊 | chat_agent | chat_agent | 导师风格回答 |

**核心设计原则：**
- **analyst 是"用户知识翻译官"的唯一责任点。** 从 Neo4j 读取用户知识档案（掌握/薄弱的算法），在 solve 模式下产出完整解题策略，在 diagnose 模式下产出代码审查指引（可用/避开的知识点 + 编码风格）。developer 永不直接读取用户知识档案——两个模式下都通过 `strategy` 字段间接获取。
- **CQRS + Redis Pub/Sub 解耦：** 推演 Worker 由 `BackgroundTasks` 调度，通过 `redis.publish(channel, sse_data)` 广播；前端通过 `redis.pubsub().subscribe()` 消费。Worker 与 HTTP 响应协程完全分离——客户端断开不中断图流转
- **分布式锁防并发：** Redis `SETNX` 对 `lock:stream:{thread_id}` 加锁（600s TTL），重复请求返回 409 Conflict。锁在 Worker 的 `finally` 块中无条件释放
- **代码安全沙箱：** Docker 执行（`network_mode="none"` / `cap_drop=["ALL"]` / `no-new-privileges` / 512MB 内存 / 0.5 CPU / 30s 超时），工作区物理隔离 → 执行 → 销毁，零残留

### 4.2 多轮对话长期记忆（PostgreSQL）

- **首轮：** 传入完整 `DevState`（14 个字段全部手工初始化），推演完成后全量写入 PostgreSQL Checkpoint
- **续轮：** 仅传增量 `{"messages": [HumanMessage("追问...")]}`，底层的 `add_messages` reducer 自动追加到历史消息列表，PostgreSQL Checkpoint 自动恢复其余全部字段（problem_description、generated_code、algorithm_strategy 等）
- **高并发连接池：** psycopg `AsyncConnectionPool`（max_size=20），由 FastAPI lifespan 统一管理生命周期
- **历史会话管理：** 侧边栏展示所有会话，点击恢复完整状态（聊天气泡 + 代码区 + QA 面板）
- **上下文窗口修剪：** 4 种策略（trim_for_intent_recognizer / trim_for_chat_agent / trim_for_developer / trim_for_qa），按 Agent 角色精准过滤

### 4.3 认知图谱 (GraphRAG)

- **后台记忆吸收：** 推演完成后，Worker 在锁保持期间静默运行 `absorb_memory_pipeline`：从 Checkpoint 还原现场 → 过滤前台对话（User + tutor/chat_agent）→ `MemoryExtractorService` LLM 结构化提取 → `GraphWriter` 写入 Neo4j（`(User)-[UNDERSTANDS]->(Concept)`）
- **多跳前置雷达：** Analyst 和 ChatAgent 执行前，调用 `GraphReader.check_prerequisites()` 查询 Neo4j，检测用户对目标算法前置知识的掌握情况。不仅返回缺失知识点列表，还返回缺失知识点内部的拓扑依赖边（`dependency_edges`），供 LLM 推理出"从哪个根源断层开始补课"
- **潜意识注入：** Tutor/ChatAgent 调用 `get_graph_memory_prompt()` 从 Neo4j 读取用户认知画像（红温指数 1-5、薄弱知识点 Top 10、工程坏习惯），包装为 `<User_Cognitive_Profile>` 标签注入系统提示词，动态调整回复策略
- **技能树可视化：** ECharts 力导向图，110 个算法节点 + 118 条前置依赖边，颜色编码掌握程度（灰=未学，橙=练习中，绿=已掌握），支持双向 BFS 搜索高亮 + 点击循环切换状态 + 一键同步至 Neo4j

### 4.4 用户体系

- **JWT 认证：** bcrypt 密码哈希 + HS256 签发 + Redis jti 吊销（滑动窗口续期，24h 过期）
- **登出即失效：** `POST /logout` → 删除 Redis jti → 令牌立即作废
- **Neo4j 同步注册：** 注册时同步在 Neo4j 创建 `(:User {id: user_id})` 节点，打通认知图谱
- **全链路异步：** `get_current_user` 依赖使用 `AsyncSession` + 异步 Redis，事件循环零阻塞

---

## 五、API 接口一览

### 认证 `/api/auth`

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/register` | 无 | 注册（username + password），MySQL + Neo4j 双写 |
| POST | `/login` | 无 | 登录，返回 JWT access_token |
| POST | `/logout` | Bearer | 登出，Redis 吊销令牌 |

### 推演 `/api/chat`

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/threads` | Bearer | 创建新会话（UUID 生成，title 首条消息截取） |
| GET | `/threads` | Bearer | 拉取历史会话列表（按 updated_at DESC） |
| POST | `/stream` | Bearer | **CQRS 流式推演**（SETNX 锁 + BackgroundTasks Worker + Redis Pub/Sub 消费） |
| GET | `/history?thread_id=` | Bearer | 拉取会话完整历史（清洗后消息 + current_code + qa_feedback） |

### 认知图谱 `/api/graph`

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/profile/{user_id}` | Bearer | 获取用户能力图谱（skills + dependencies + frustration_level + bad_smells） |
| POST | `/mastery` | 无 | 手动更新技能熟练度（3 态：mastered/progressing/unlearned） |
| DELETE | `/mastery/{user_id}` | Bearer | 重置用户图谱（删除所有 UNDERSTANDS 关系） |

### 用户 `/api/users`

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/{user_id}` | Bearer | 查询用户基本信息 |

### 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |

---

## 六、前端页面

| 页面 | 技术栈 | 功能 |
|---|---|---|
| `login.html` | Vue 2 + Element UI | 登录/注册双 Tab，Canvas 验证码，`localStorage` 存储 token + userId |
| `index.html` | Vue 2 + Element UI + highlight.js + KaTeX + marked.js | 三栏工作台：深色侧边栏（会话列表 + 折叠）+ 聊天气泡（Markdown/LaTeX 渲染）+ 代码沙箱区（highlight.js 语法高亮 + 可折叠终端）。流式采用 `ReadableStream` + 手动 SSE 解析，支持 AbortController 取消 |
| `profile.html` | Vue 2 + Element UI + ECharts 5 | 算法认知 DAG 可视化：力导向图 + 颜色编码 + 点击切换熟练度 + 双向 BFS 搜索高亮 + 同步至雷达 |

---

## 七、项目亮点

### 7.1 工业级 CQRS 流式架构

传统 SSE 推演直接把跑图协程绑在 HTTP 响应上——客户端断开 → 协程取消 → 状态脏污。本项目的方案：

```
POST /stream → SETNX 抢锁 → BackgroundTasks 启动 Worker（解耦！）
Worker 跑图 → redis.publish(channel, sse_data) → 推送 [EOF] → 记忆吸收 → 释放锁
前端消费者 → redis.pubsub().subscribe(channel) → listen() → yield SSE
```

**收益：** 客户端关闭/网络断开不中断图流转；同一 thread 并发请求被 409 拒绝；锁在 Worker finally 中无条件释放；记忆吸收在锁保持期间完成，数据一致。

### 7.2 多轮对话长期记忆（PostgreSQL）

- **生产级存储：** AsyncPostgresSaver + psycopg `AsyncConnectionPool`（max_size=20），替代开发期的 SQLite
- **增量追加：** 续轮仅传 `{"messages": [HumanMessage(...)]}`，PostgreSQL 自动恢复全部历史状态，零冗余传输
- **上下文修剪：** 对话型 Agent 保留白名单 + 3 轮滑动窗口（max 7 条消息），执行型 Agent 极简上下文防重试雪球

### 7.3 GraphRAG 认知图谱 + 多跳雷达

```
推演完成 → LLM 提取认知 → Neo4j 写入 (User)-[UNDERSTANDS]->(Concept)
         → 下次推演 → 多跳雷达扫描前置知识 → 返回缺失节点 + 内部拓扑边
         → 分析师变更为"学习路径架构师" → 输出渐进式补课大纲
         → Tutor/ChatAgent 注入认知画像 → 动态调整教学策略
```

每次推演都在静默生长个性化知识图谱。Agent 在解题/答疑前自动多跳查询用户薄弱点及其依赖关系，从"根源断层"开始引导补课。

### 7.4 Clean Architecture 分层

```
api/routes/     ← 路由层：鉴权 + 参数校验 + 调 service + 返回响应（~100 行/文件）
services/       ← 领域服务层：run_graph_worker, absorb_memory_pipeline, sse_consumer
core/utils/     ← 工具层：format_sse, extract_node_content, clean_messages, trim_for_*
core/engine/    ← 引擎层：LLM 连接池, Docker 沙箱, 状态定义
db/             ← 基础设施层：PostgreSQL/MySQL/Redis/Neo4j 连接池
```

路由文件从 400 行"上帝文件"精简为 147 行纯端点。服务层可独立单测，工具函数可跨模块复用。

### 7.5 四引擎数据库

| 引擎 | 用途 | 驱动 | 连接池 |
|---|---|---|---|
| MySQL | 用户 / 会话 CRUD | SQLAlchemy 2.0 (sync + async) | 双引擎，20+10 |
| PostgreSQL | LangGraph Checkpoint 长期记忆 | psycopg 3 (async) | AsyncConnectionPool, max_size=20 |
| Redis | JWT 滑动窗口 (6379:1) + 分布式锁/Pub/Sub (6380:1) | redis-py (sync + async) | 分离部署 |
| Neo4j | 认知图谱存储 + 多跳雷达查询 | neo4j async driver | 50 连接，30s 获取超时 |

### 7.6 安全沙箱

- 工作区物理隔离（`shutil.copytree` 到临时目录）
- Docker 断网执行（`network_mode="none"`）
- 无特权（`cap_drop=["ALL"]`，`security_opt=["no-new-privileges:true"]`）
- 资源限制（512MB 内存，0.5 CPU，30s 超时 + 3s kill grace）
- 执行完毕立即销毁容器 + 临时目录（零残留）

### 7.7 高可用保障

- LLM 调用指数退避重试：4 次，2s → 4s → 8s → 16s（仅捕获 `ConnectionError` + `TimeoutError`）
- 记忆提取失败返回兜底空 `ExtractedGraphMemory`（frustration=1，空列表），不阻断业务
- 图数据库读取失败优雅降级返回空字符串，不阻断 Agent 主流程
- PostgreSQL 连接池 `pool_pre_ping` + 连接获取超时保护

---

## 八、部署与启动

### 前置依赖

- Python 3.11+
- MySQL 8.0（用户/会话数据）
- PostgreSQL 16（LangGraph Checkpoint 长期记忆）
- Redis 7.x（端口 6379 鉴权 + 端口 6380 流式 Pub/Sub）
- Neo4j 5.x（bolt://localhost:7687，认知图谱）
- Docker（代码安全沙箱）

### 环境变量（`.env`）

```env
# LLM
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com

# LangSmith 追踪
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_xxx
LANGCHAIN_PROJECT=DevSwarm_MVP

# MySQL
MYSQL_USER=root
MYSQL_PASSWORD=xxx
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DB=devswarm

# PostgreSQL (Checkpoint)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=admin
POSTGRES_PASSWORD=xxx
POSTGRES_DB=main_db
POSTGRES_SSLMODE=disable

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=1

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xxx

# JWT
SECRET_KEY=devswarm-jwt-secret-change-in-production
```

### 启动命令

```bash
# 后端
cd devswarm_core
pip install -r requirements.txt
python main.py
# → http://0.0.0.0:8000
# → Swagger UI: http://localhost:8000/docs

# 前端（静态文件）
cd devswarm-ui
# 直接用浏览器打开 index.html / login.html，或使用任意静态文件服务
```

### 首次启动数据库准备

```sql
-- MySQL
CREATE DATABASE devswarm CHARACTER SET utf8mb4;

-- PostgreSQL
CREATE DATABASE main_db;
-- 表由 LangGraph checkpointer.setup() 自动创建（checkpoints, checkpoint_writes, checkpoint_blobs）

-- Neo4j
-- 知识图谱节点与关系由 schemas/algorithm_data.py 的基建数据脚本初始化
```

---

## 九、未来规划

- [ ] WebSocket 替代 Redis Pub/Sub（减少中间件依赖，简化部署）
- [ ] Alembic 数据库迁移管理（MySQL + PostgreSQL 双轨）
- [ ] 单元测试 + 集成测试覆盖（pytest + pytest-asyncio）
- [ ] Docker Compose 一键部署（6 容器：FastAPI + MySQL + PostgreSQL + Redis × 2 + Neo4j）
- [ ] 算法题目的多模态支持（图片/PDF 上传自动解析）
- [ ] 团队协作功能（多人共享认知图谱，跨用户知识迁移）
- [ ] LLM Provider 抽象层（支持 OpenAI / Claude / 本地模型热切换）
