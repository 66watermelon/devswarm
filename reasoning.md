# DevSwarm 架构决策记录 (ADR)

> 记录项目中的关键架构决策：背景、方案、为什么选这个、为什么不选备选。

---

## ADR-1: 为什么用 LangGraph 而不是手写 Agent 循环

**背景：** 需要一个编排 6 个 Agent 的执行引擎。它们之间有条件路由（solve vs diagnose）、工具调用回路（developer ⇄ tools）、重试熔断（QA fail <3 次重新进入 developer）。

**方案：** 使用 LangGraph 的 `StateGraph`，定义节点 + 条件边 + 普通边。自建 `route_after_*` 函数处理路由逻辑。

**为什么选这个：**

- **状态管理内建：** `DevState` TypedDict 通过 `add_messages` reducer 自动合并消息，不需要手写 append/merge 逻辑
- **Checkpoint 原生支持：** `AsyncPostgresSaver` 一行注入，多轮对话记忆零额外代码
- **工具调用回路自动：** `ToolNode` + `add_conditional_edges` 自动检测 `tool_calls` → 执行 → 回传
- **可视化：** LangSmith 自动记录每个节点 I/O，调试效率秒杀手写 Agent 的 `print` 大法

**为什么不选手写 Agent 循环：**

手写 `while True: agent.run(state)` 需要自己管理状态持久化、工具调用循环、错误恢复。等价于重新实现半个 LangGraph，且写出来一定比 LangGraph 的实现差。

---

## ADR-2: 为什么 PostgreSQL Checkpoint 而不是 Redis / SQLite

**背景：** 需要持久化每个 `thread_id` 的完整 `DevState`（~16 个字段 + 消息历史）。多轮对话、跨模式切换、诊断回声都依赖 checkpoint 恢复状态。

**方案：** 使用 `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` + psycopg `AsyncConnectionPool`。

**为什么选 PostgreSQL：**

- **生产级可靠：** SQLite 在开发期够用但无法支持多 worker 并发写入。PostgreSQL 连接池 + `pool_pre_ping` 适合生产环境
- **Schema 自动管理：** `checkpointer.setup()` 自动建表，不需要手写 DDL
- **与 MySQL 共存：** MySQL 管业务数据（用户/会话），PostgreSQL 管 Agent 记忆，职责分离

**为什么不选 Redis：** Redis 的内存特性意味着 checkpoint 数据可能因内存淘汰而丢失。对于"一个月后回来继续聊"这种长周期记忆场景，磁盘持久化是刚需。

**为什么不选 SQLite（长期）：** SQLite 在单 worker 下工作正常，但多 worker 场景下写锁冲突会导致 LangGraph 的 `astream` 阻塞。

---

## ADR-3: 为什么 CQRS + Redis Pub/Sub 而不是直连 SSE

**背景：** LangGraph 推演耗时 ~150s。如果直接绑在 HTTP 协程上，客户端断开（用户关闭页面）→ 协程被取消 → Worker 中断 → checkpoint 状态可能不完整。

**方案：** 使用 CQRS 模式——`BackgroundTasks` 启动 Worker（命令端），前端通过 `redis.pubsub().subscribe()` 消费 SSE 事件（查询端）。Worker 与 HTTP 响应完全解耦。

**为什么选这个：**

- **客户端断开安全：** Worker 不受 HTTP 连接影响，继续跑完图并存入 checkpoint
- **并发隔离：** Redis `SETNX` 锁防止同一 thread 同时跑两个 Worker
- **优雅终止：** Worker 发布 `[EOF]` 后释放锁，前端消费者收到 `[EOF]` 后 break

**为什么不选直连 SSE：** 直连方案下，Worker `yield` 的每一步都依赖 HTTP 连接存活。客户端断开 → `CancelledError` → 图流转中断 → 状态可能髒。这在用户关闭页面重新打开时就会出现"推演到一半不见了"的体验问题。

---

## ADR-4: 为什么 analyst 是唯一读 user_memory_context 的 Agent

**背景：** `user_memory_context` 包含 Neo4j 读出的用户知识档案（掌握哪些算法、薄弱于哪些知识点）。这个信息应该被谁使用？

**方案：** 只有 `analyst` 读取 `user_memory_context`，将其翻译为 `algorithm_strategy`。其他 Agent 通过 `strategy` 间接获取用户知识信息。

**为什么选这个：**

- **单一翻译点：** 如果 developer、qa、tutor 都直接读 `user_memory_context`，每个节点需要独立理解"用户 X 薄弱于 DP"的含义并自行决策。analyst 统一翻译后，其他节点只需遵循 strategy
- **接口稳定：** `strategy` 字段的语义在两个模式下不同（solve→算法策略，diagnose→审查指引），但 producer 和 consumer 之间的契约不变
- **二种模式下策略不同但契约一致：** solve 下 strategy 含完整算法思路，diagnose 下 strategy 含代码审查指引。developer 不需要根据 mode 切换读法——strategy 已经由 analyst 做了差异化

**为什么不选多方读取：** 多方读取会导致同一数据在多处被重写、多处理解不一致。改一行 Neo4j 查询的输出格式，需要同步改 4 个 Agent 的 prompt，维护成本爆炸。

---

## ADR-5: 为什么 mode 用三值而不是 user_intent + mode 两字段

**背景：** 最初的设计用 `user_intent`（task/chat）+ `mode`（solve/diagnose）两个字段来表示"这是哪种对话"。实际运行时，两字段本质上是同一个三维分类（solve / diagnose / chat），只是被拆成了两层路由。

**方案：** 合并为 `mode: Literal["solve", "diagnose", "chat"]` 单一字段。intent_recognizer 一次输出三值分类，`route_after_intent` 直接读 mode。

**为什么选这个：**

- **减少路由层：** 原来 intent_recognizer → route_after_intent 读 user_intent → analyst → route_after_analysis 再读 mode。现在一次路由完成
- **字段数更少：** DevState 从 17 个减少到 16 个，消除一个共识成本（"user_intent 和 mode 有什么区别？"）
- **语义清晰：** 三值枚举名就是用户能理解的行为——solve 即解题、diagnose 即诊断、chat 即聊天

---

## ADR-6: 为什么用内存修剪器而不是直接截断 messages

**背景：** 多轮对话后 `messages` 可能积累数十条。直接把全量消息塞进 LLM prompt 会超 token 限制。

**方案：** 4 种修剪策略按 Agent 角色定制——intent 只看最后一条、对话型 Agent 用白名单 + 滑动窗口、developer 只留系统 + 最新 QA 报错、qa 从最后一个 developer 消息截断。

**为什么选这个：**

- **角色匹配：** 对话型 Agent 需要多轮上下文（3 轮够用），执行型 Agent 需要专注（不浪费 token 在无关历史）
- **抗雪球效应：** developer 被 QA 打回重试时，如果保留 3 轮 developer 历史，每次新 prompt 都是"旧代码 + 旧错误 + 新指令"的叠加。极限模式（只留最新 QA 报错）避免 token 膨胀

**为什么不选一刀切截断：** 简单取最后 N 条消息会导致 analyst 看不到用户上轮的分析策略、developer 看到无关的 chat 历史、qa 被 analyst 的分析干扰判题。

---

## ADR-7: 为什么 user_code 要作为 HumanMessage 写入 messages

**背景：** `user_code` 原本只存在 `state["user_code"]` 字段里。用户在同一 thread 内二次上传代码时，旧代码被覆盖。agent 无法对比两次上传的代码。

**方案：** 每次上传 `user_code` 时，除了写入 `state["user_code"]`，同时作为带 `name="code_upload"` 标记的 `HumanMessage` 插入 messages 流。checkpoint 持久化后，旧代码永不丢失。

**为什么选这个：**

- **永不被覆盖：** 代码成为 messages 中的一条消息，checkpoint 追加不覆盖
- **不影响现有 trimmer：** 所有 trimmer 要么按 HumanMessage 类型保留（对话型），要么按位置丢弃（执行型），code_upload 完全遵循现有规则
- **intent_recognizer 不受影响：** 代码消息插入在 prompt 之前，`messages[-1]` 始终是用户最新文字输入

**为什么不选专用 "code_history" 数组：** 新增 state 字段需要新的修剪规则、新的 checkpoint 迁移。复用 messages 机制零成本、零迁移。
