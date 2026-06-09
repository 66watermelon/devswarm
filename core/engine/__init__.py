"""
DevSwarm 引擎包 (Engine)

包含平台的核心基础设施：
- config:       全局配置（API Key / Base URL / 模型名）
- state:        LangGraph 状态定义（DevState）
- exceptions:   统一异常体系
- llm_factory:  LLM 连接池（按角色预实例化）
- sandbox:      Docker 安全代码执行沙箱
"""
