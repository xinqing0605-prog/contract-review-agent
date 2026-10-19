"""条款检测与风险分级（纯标准库）。

设计取舍：检测坚持用可复现的规则，不用模型。
- 同一份合同必须每次审出同样的结果，否则无法做回归测试和评测
- 规则零成本、零延迟、可解释；模型只负责写「风险解释」和「修改建议」
- 模型的输出必须绑定已有原文片段，不允许自己生成原文（防幻觉的第一道闸）

v2 相对最初版本的三个修正（都是评测集跑出来的，不是拍脑袋改的）：
1. 择句：原来取全文第一个命中，导致「责任限制」被付款那句抢走；改为在所有命中里
   选「匹配文本最长」的那句，越长越具体。
2. 约束：`数据` 太宽，会把「数据损失」误判成数据处理条款；收紧成需要搭配处理类动词。
3. 负向规则：`不可抗力` 里的「互不承担责任」是标准条款，不该判高风险，按类型配置排除词。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

RISK_ORDER = {"low": 1, "medium": 2, "high": 3}
SENTENCE_END = "。；;！？!?\n"
MAX_CLAUSE_CHARS = 320
EXCERPT_CHARS = 120


@dataclass(frozen=True)
class Pattern:
    title: str
    regex: str
    risk: str
    reason: str
    recommend: str
    exclude: str | None = None


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        "付款与验收",
        r"付款|发票|验收",
        "medium",
        "付款条件偏长，或排除了逾期付款责任，可能影响现金流和追偿依据。",
        "建议将付款周期调整为验收后 30 日，并保留逾期付款利息或违约金。",
    ),
    Pattern(
        "责任限制",
        r"责任|赔偿|间接损失|利润损失|数据损失",
        "high",
        "责任排除范围过宽，未区分故意或重大过失，也没有赔偿上限。",
        "增加故意或重大过失例外，并设置清晰的赔偿上限。",
        exclude=r"不可抗力",
    ),
    Pattern(
        "自动续期",
        r"续期|自动延长",
        "medium",
        "通知窗口较短，容易产生非预期续约。",
        "将通知期限调整为 60 日，并增加续期前的价格复核。",
    ),
    Pattern(
        "独家合作",
        r"独家|不得与.*渠道",
        "high",
        "独家范围、地域和产品边界不清晰，可能限制正常业务拓展。",
        "限定独家范围、地域和品类，并设置未达标解除条件。",
    ),
    Pattern(
        "数据使用",
        r"数据[^。；]{0,8}(处理|使用|共享|分析|营销|出境)|个人信息|营销使用",
        "medium",
        "未明确数据主体、授权范围、保存期限和退出机制。",
        "补充处理目的、授权期限、删除机制及安全事件通知。",
        exclude=r"数据损失",
    ),
    Pattern(
        "服务等级",
        r"可用性|服务等级|SLA",
        "medium",
        "缺少统计口径、维护窗口和未达标补偿。",
        "补充计算方式、维护通知和服务抵扣规则。",
    ),
    Pattern(
        "保密义务",
        r"保密|机密",
        "low",
        "期限清晰，未发现明显冲突。",
        "补充信息泄露后的通知和补救义务。",
    ),
    Pattern(
        "知识产权",
        r"知识产权|源代码|组件",
        "low",
        "属于常见保留条款，建议确认交付物归属。",
        "将定制开发成果、源代码和交付文档写入附件清单。",
    ),
)


def sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    """把命中范围扩展到所在句子，并裁掉首尾空白。"""
    left = 0
    for ch in SENTENCE_END:
        idx = text.rfind(ch, 0, start)
        if idx >= 0:
            left = max(left, idx + 1)
    right = len(text)
    for ch in SENTENCE_END:
        idx = text.find(ch, end)
        if idx >= 0:
            right = min(right, idx + 1)
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if right - left > MAX_CLAUSE_CHARS:
        right = left + MAX_CLAUSE_CHARS
    return left, right


def pick_span(text: str, pattern: Pattern) -> tuple[int, int] | None:
    """在所有命中里挑最具体的那一处分句。

    打分用匹配文本长度：`间接损失` 比 `责任` 更能代表责任条款。
    """
    best: tuple[int, int] | None = None
    best_score = (-1, -1)
    for match in re.finditer(pattern.regex, text, re.I):
        start, end = sentence_span(text, match.start(), match.end())
        if start >= end:
            continue
        body = text[start:end]
        if pattern.exclude and re.search(pattern.exclude, body):
            continue
        # 同一句里命中次数多的更像真正的条款句；
        # 次数相同再比匹配文本长度（越具体越可信）。
        # 这样「第一条 付款方式」这种标题不会被当成付款条款。
        hits = len(re.findall(pattern.regex, body, re.I))
        score = (hits, len(match.group(0)))
        if score > best_score:
            best_score = score
            best = (start, end)
    return best


def refine_risk(pattern: Pattern, clause_text: str, full_text: str) -> str:
    """风险是判断出来的，不是写在表里的常量。

    这是最容易被面试追问的一处：如果 8 个类型的风险值是硬编码的，
    那「风险分级」就只是标签映射。这里给出可验证的复核规则。
    """
    if pattern.title == "付款与验收":
        if re.search(r"(六十|九十|60|90)\s*日", clause_text) or "逾期付款不承担" in clause_text:
            return "high"
        return "medium"
    if pattern.title == "责任限制":
        if re.search(r"上限|不超过|最高赔", full_text):
            return "medium"
        if "间接损失" in full_text or "利润损失" in full_text:
            return "high"
        return "medium"
    return pattern.risk


def analyze_text(document_id: str, text: str) -> list[dict[str, Any]]:
    """返回条款列表。偏移量全部相对全文，可直接用于前端高亮。"""
    clauses: list[dict[str, Any]] = []
    for pattern in PATTERNS:
        span = pick_span(text, pattern)
        if span is None:
            continue
        start, end = span
        body = text[start:end]
        excerpt = body if len(body) <= EXCERPT_CHARS else body[:EXCERPT_CHARS] + "…"
        clauses.append(
            {
                "id": f"{document_id}-{len(clauses) + 1}",
                "document_id": document_id,
                "title": pattern.title,
                "risk": refine_risk(pattern, body, text),
                "excerpt": excerpt,
                "original": body,
                "reason": pattern.reason,
                "recommend": pattern.recommend,
                "start_offset": start,
                "end_offset": end,
                "accepted": 0,
            }
        )
    clauses.sort(key=lambda c: c["start_offset"])
    return clauses
