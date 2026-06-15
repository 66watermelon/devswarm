<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangGraph-0.3-1c3c3c?logo=langchain" alt="LangGraph">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Neo4j-5.x-4581C3?logo=neo4j" alt="Neo4j">
  <img src="https://img.shields.io/badge/Redis-7.x-DC382D?logo=redis" alt="Redis">
  <img src="https://img.shields.io/badge/tests-48%20passed-brightgreen" alt="tests">
</p>

# DevSwarm — AI 算法私教

> Multi-Agent 协同推演平台。出题、解题、诊断代码、推荐学习路径。

代码在 Docker 沙箱里真跑验证，Neo4j 认知图谱追踪你的掌握程度。

## 快速开始

```bash
git clone https://github.com/66watermelon/devswarm.git && cd devswarm
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # 填入 API Key 和数据库密码
python main.py         # → http://localhost:8000
```

## 三种模式

| 模式 | 干什么 |
|---|---|
| **solve** | 解题：分析策略 → 写代码 → 沙箱测试 → 题解 |
| **diagnose** | 诊断：沙箱测你的代码 → 指出问题 → 自动修复 |
| **chat** | 答疑 + 推荐学习路径 |

## 文档

- `项目技术文档.md` — 完整架构设计、数据流、API 接口
- `reasoning.md` — 架构决策记录 (ADR)

## 技术栈

FastAPI / LangGraph / DeepSeek / PostgreSQL / Neo4j / Redis / Docker / Vue 2
