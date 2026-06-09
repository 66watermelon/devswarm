from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

# ==========================================
# 1. 业务状态枚举区 (替代 Literal，彻底消灭硬编码)
# ==========================================
class ConceptCategory(str, Enum):
    """知识概念的大类划分"""
    DATA_STRUCTURE = "数据结构"
    ALGORITHM = "算法思维"
    ENGINEERING = "工程习惯"
    LANGUAGE = "语言特性"

class MasteryStatus(str, Enum):
    """知识掌握程度评估状态"""
    MASTERED = "mastered"
    PROGRESSING = "progressing"
    FAILED = "failed"

# ==========================================
# 2. 认知图谱实体与关系模具 (DTO)
# ==========================================
class ConceptNode(BaseModel):
    """算法知识点或工程概念实体"""
    name: str = Field(
        ...,
        description="极度标准化的术语，如 '动态规划', '边界条件', '空指针校验'"
    )
    category: ConceptCategory = Field(
        ...,
        description="概念所属大类"
    )

class SkillAssessment(BaseModel):
    """技能掌握度评估（支持正向与负向）"""
    concept_name: str = Field(
        ...,
        description="必须与 ConceptNode 中的 name 对应"
    )
    # 将 Literal 替换为 MasteryStatus 枚举
    status: MasteryStatus = Field(
        ...,
        description="mastered(完全掌握/写出最优解), progressing(有瑕疵但能写出), failed(完全不会/严重报错)"
    )
    error_pattern: Optional[str] = Field(
        None,
        description="如果 status 是 failed 或 progressing，提取具体的错误模式（如 'while死循环'）"
    )
    context_summary: str = Field(
        ...,
        description="一句话总结上下文，如 '在手撕 LRU 缓存时遗漏了双向链表断尾操作'"
    )

class UserState(BaseModel):
    """用户心智与行为画像"""
    frustration_level: int = Field(
        ...,
        description="用户当前的挫败感/红温指数 (1-5)。1代表轻松开心，5代表极其暴躁/崩溃/想要放弃"
    )
    bad_code_smells: List[str] = Field(
        default_factory=list,
        description="本轮对话中暴露的工程坏味道，如 '变量命名随意(a, b, c)', '不写边界return'"
    )

# ==========================================
# 3. 交付容器
# ==========================================
class ExtractedGraphMemory(BaseModel):
    """单次对话的全局认知切片（喂给大模型的终极模具）"""
    concepts: List[ConceptNode] = Field(
        default_factory=list,
        description="本次提取到的所有概念"
    )
    assessments: List[SkillAssessment] = Field(
        default_factory=list,
        description="对这些概念的掌握度评估"
    )
    user_state: UserState = Field(
        ...,
        description="用户的心智与行为状态画像"
    )