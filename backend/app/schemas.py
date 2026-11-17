"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。"""

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    """状态动作使用独立契约，避免与登记的 values 载荷混用。"""

    action: str
    remark: str | None = None


class RecomputePayload(BaseModel):
    """阈值重算请求：新阈值、阈值区间与重新判定范围，旧阈值缺省取策略当前值。"""

    新阈值: float
    旧阈值: float | None = None
    阈值下界: float | None = None
    阈值上界: float | None = None
    去重算法: str | None = None
    业务键列: str | None = None
    保留顺序: str | None = None
    重新判定范围: str | None = None
    范围批次: list[str] | None = None
    幂等键: str | None = None


class SetCurrentVersionPayload(BaseModel):
    """在冻结版与最新版之间切换当前去重版本。"""

    策略版本: str


class LandingPayload(BaseModel):
    """存储落地读取已确认报告生成去重落地清单，落地版本必须与报告版本一致。"""

    报告编号: str
    存储配置编号: str
    策略版本: str | None = None



class TargetsiteEntry(BaseModel):
    """目标站点明细结构。"""

    field_0: str | None = None  # 站点编号
    field_1: str | None = None  # 站点名称
    field_2: str | None = None  # 入口URL
    field_3: str | None = None  # 请求方法
    field_4: str | None = None  # 请求头模板
    field_5: str | None = None  # 字符编码
    field_6: str | None = None  # 重试上限
    field_7: str | None = None  # 抓取间隔

class SelectorEntry(BaseModel):
    """选择器规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 归属站点
    field_2: str | None = None  # 列表选择器
    field_3: str | None = None  # 详情选择器
    field_4: str | None = None  # 字段选择器
    field_5: str | None = None  # 分页参数
    field_6: str | None = None  # 等待条件
    field_7: str | None = None  # 字符编码

class CrawlerEntry(BaseModel):
    """爬虫任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 任务名称
    field_2: str | None = None  # 关联站点
    field_3: str | None = None  # 关联规则
    field_4: str | None = None  # 并发线程
    field_5: str | None = None  # 调度周期
    field_6: str | None = None  # 超时秒数
    field_7: str | None = None  # 下发批次

class ProxyEntry(BaseModel):
    """代理节点明细结构。"""

    field_0: str | None = None  # 节点编号
    field_1: str | None = None  # IP地址
    field_2: str | None = None  # 端口号
    field_3: str | None = None  # 协议类型
    field_4: str | None = None  # 匿程度
    field_5: str | None = None  # 响应延迟
    field_6: str | None = None  # 存活检测
    field_7: str | None = None  # 所属区域

class AntiblockEntry(BaseModel):
    """反爬策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 策略名称
    field_2: str | None = None  # 触发条件
    field_3: str | None = None  # 延迟范围
    field_4: str | None = None  # UA伪装
    field_5: str | None = None  # Referer生成
    field_6: str | None = None  # Cookie策略
    field_7: str | None = None  # 熔断阈值

class ScheduleEntry(BaseModel):
    """调度计划明细结构。"""

    field_0: str | None = None  # 计划编号
    field_1: str | None = None  # 关联任务
    field_2: str | None = None  # Cron表达式
    field_3: str | None = None  # 执行窗口
    field_4: str | None = None  # 重试策略
    field_5: str | None = None  # 失败通知
    field_6: str | None = None  # 最大并发
    field_7: str | None = None  # 是否启用

class ExtractorEntry(BaseModel):
    """提取模板明细结构。"""

    field_0: str | None = None  # 模板编号
    field_1: str | None = None  # 模板名称
    field_2: str | None = None  # 输入URL
    field_3: str | None = None  # 字段映射
    field_4: str | None = None  # 清洗规则
    field_5: str | None = None  # 输出格式
    field_6: str | None = None  # 版本号
    field_7: str | None = None  # 生效批次

class ValidateEntry(BaseModel):
    """校验规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 校验字段
    field_2: str | None = None  # 期望格式
    field_3: str | None = None  # 空值阈值
    field_4: str | None = None  # 重复判定
    field_5: str | None = None  # 异常策略
    field_6: str | None = None  # 阻断级别
    field_7: str | None = None  # 校验批次

class RetryEntry(BaseModel):
    """重试策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 适用任务
    field_2: str | None = None  # 最大重试
    field_3: str | None = None  # 退避类型
    field_4: str | None = None  # 退避系数
    field_5: str | None = None  # 幂等标识
    field_6: str | None = None  # 状态记录
    field_7: str | None = None  # 最后更新

class StorageEntry(BaseModel):
    """存储配置明细结构。"""

    field_0: str | None = None  # 配置编号
    field_1: str | None = None  # 存储类型
    field_2: str | None = None  # 连接信息
    field_3: str | None = None  # 分区策略
    field_4: str | None = None  # 压缩格式
    field_5: str | None = None  # 保存天数
    field_6: str | None = None  # 备份副本
    field_7: str | None = None  # 清理策略

class DedupEntry(BaseModel):
    """去重策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 业务键列
    field_2: str | None = None  # 去重算法
    field_3: str | None = None  # 对比窗口
    field_4: str | None = None  # 相似阈值
    field_5: str | None = None  # 保留顺序
    field_6: str | None = None  # 增量模式
    field_7: str | None = None  # 生效批次

class QualityEntry(BaseModel):
    """质量指标明细结构。"""

    field_0: str | None = None  # 指标编号
    field_1: str | None = None  # 指标名称
    field_2: str | None = None  # 统计口径
    field_3: str | None = None  # 阈值下界
    field_4: str | None = None  # 阈值上界
    field_5: str | None = None  # 统计周期
    field_6: str | None = None  # 样本数量
    field_7: str | None = None  # 达标率

class MonitorEntry(BaseModel):
    """监控大盘明细结构。"""

    field_0: str | None = None  # 大盘编号
    field_1: str | None = None  # 关联任务
    field_2: str | None = None  # 采集速率
    field_3: str | None = None  # 成功率
    field_4: str | None = None  # 平均延迟
    field_5: str | None = None  # 内存占用
    field_6: str | None = None  # 错误次数
    field_7: str | None = None  # 观测时段

class AlertEntry(BaseModel):
    """告警规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 监控对象
    field_2: str | None = None  # 告警条件
    field_3: str | None = None  # 通知渠道
    field_4: str | None = None  # 通知模板
    field_5: str | None = None  # 重复间隔
    field_6: str | None = None  # 生效时段
    field_7: str | None = None  # 值班人员

class ApigateEntry(BaseModel):
    """API配置明细结构。"""

    field_0: str | None = None  # 配置编号
    field_1: str | None = None  # 端点路径
    field_2: str | None = None  # 请求方法
    field_3: str | None = None  # 鉴权方式
    field_4: str | None = None  # 速率限制
    field_5: str | None = None  # 响应缓存
    field_6: str | None = None  # 调用配额
    field_7: str | None = None  # 版本控制

class ArchiveEntry(BaseModel):
    """归档策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 数据来源
    field_2: str | None = None  # 归档周期
    field_3: str | None = None  # 归档格式
    field_4: str | None = None  # 保留年限
    field_5: str | None = None  # 压缩级别
    field_6: str | None = None  # 索引规则
    field_7: str | None = None  # 清理策略

class TemplateEntry(BaseModel):
    """采集模板明细结构。"""

    field_0: str | None = None  # 模板编号
    field_1: str | None = None  # 模板名称
    field_2: str | None = None  # 适用站点
    field_3: str | None = None  # 站点类型
    field_4: str | None = None  # 提取逻辑
    field_5: str | None = None  # 内置规则
    field_6: str | None = None  # 使用次数
    field_7: str | None = None  # 作者来源

class FlowlineEntry(BaseModel):
    """流程编排明细结构。"""

    field_0: str | None = None  # 流程编号
    field_1: str | None = None  # 流程名称
    field_2: str | None = None  # 步骤序列
    field_3: str | None = None  # 输入站点
    field_4: str | None = None  # 输出目标
    field_5: str | None = None  # 失败处理
    field_6: str | None = None  # 触发条件
    field_7: str | None = None  # 版本号
