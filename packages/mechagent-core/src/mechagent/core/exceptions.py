"""MechAgent 核心层异常定义。"""


class MechAgentCoreError(Exception):
    """核心工具层基础异常。"""


class SolverError(MechAgentCoreError):
    """求解器执行失败异常。"""


class MeshError(MechAgentCoreError):
    """网格生成或网格质量检查失败异常。"""


class PostProcError(MechAgentCoreError):
    """后处理阶段失败异常。"""


class CADError(MechAgentCoreError):
    """CAD 形体导入、修复或特征识别失败异常。"""


class ExecutorError(MechAgentCoreError):
    """作业执行器提交、轮询、取消或结果获取失败异常。"""


class ValidationError(MechAgentCoreError):
    """标准验证算例失败异常。"""
