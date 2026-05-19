from __future__ import annotations

from dataclasses import dataclass

import config_data as config


@dataclass
class OutfitConstraints:
    gender: str
    style: str
    body: str
    scene: str
    budget: str


def build_constraints(
    *,
    gender: str,
    style: str,
    body: str,
    scene: str,
    budget: str,
) -> OutfitConstraints:
    return OutfitConstraints(
        gender=gender or "",
        style=style or "",
        body=body or "",
        scene=scene or "通用场景",
        budget=budget or "不限预算",
    )


def _must_have_lines(constraints: OutfitConstraints) -> list[str]:
    lines = []
    if constraints.scene and constraints.scene != "通用场景":
        lines.append(f"- 场景约束：优先满足「{constraints.scene}」下的实穿与得体。")
    if constraints.budget and constraints.budget != "不限预算":
        lines.append(f"- 预算约束：推荐需控制在「{constraints.budget}」预算档位内。")
    if constraints.body:
        lines.append(f"- 体型约束：结合「{constraints.body}」提供扬长避短建议。")
    if constraints.style:
        lines.append(f"- 风格约束：整体风格与「{constraints.style}」保持一致。")
    return lines


def inject_constraints_prompt(user_input: str, constraints: OutfitConstraints) -> str:
    lines = _must_have_lines(constraints)
    if not lines:
        return user_input
    return (
        f"{user_input}\n\n"
        "【可解释约束（硬约束优先）】\n"
        + "\n".join(lines)
        + "\n请在建议中自然体现这些约束并解释原因。"
    )


def stabilize_output(text: str) -> str:
    output = text or ""
    if "⛅" not in output:
        output = "⛅ 【场景与温度感知】\n已结合你的场景信息生成建议。\n\n" + output
    if "✨" not in output:
        output += "\n\n✨ 【主理人 OOTD 灵感】\n建议围绕基础款与配色层次构建穿搭。"
    if "💡" not in output:
        output += "\n\n💡 【小衣私藏贴士】\n先确保版型合身，再做风格强化，效果更稳定。"
    signature = config.assistant_signature
    if signature not in output:
        output += f"\n\n{signature}"
    return output


def score_alignment(constraints: OutfitConstraints, text: str) -> int:
    score = 0
    text = text or ""
    if constraints.scene and constraints.scene in text:
        score += config.scene_weight
    if constraints.style and constraints.style in text:
        score += config.style_weight
    if constraints.budget != "不限预算" and constraints.budget in text:
        score += config.budget_weight
    if constraints.body and constraints.body in text:
        score += config.body_weight
    return score
