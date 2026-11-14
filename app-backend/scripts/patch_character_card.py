"""通用角色卡提示词修缮与注入工具（支持 .png 与 .json，无损保留图像与扩展字段）。"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from services.conversation.prompting.compiler import compile_dialogue_examples
from services.parse import (
    _validate_card_object,
    read_png_card_payloads,
    write_png_card_payloads,
)


def apply_patch_spec(card_payload: dict, patch_spec: dict) -> dict:
    """对单张角色卡 JSON 对象应用修缮规则（兼容 V2 data 包装与扁平对象）。"""
    payload = deepcopy(card_payload)
    target = _validate_card_object(payload)

    # 1. 字段直接覆盖 (set)
    for field, value in (patch_spec.get("set") or {}).items():
        target[field] = value
        if field == "system_prompt" and "system_prompt_override" in target:
            target["system_prompt_override"] = value

    # 2. 精确子串替换 (replace)
    for field, rules in (patch_spec.get("replace") or {}).items():
        current = str(target.get(field) or "")
        for rule in rules:
            old_text = rule["target"]
            new_text = rule["replacement"]
            if old_text not in current:
                raise ValueError(f"字段 '{field}' 中未找到待替换片段: {old_text[:40]!r}")
            current = current.replace(old_text, new_text)
        target[field] = current
        if field == "system_prompt" and "system_prompt_override" in target:
            target["system_prompt_override"] = current

    # 3. 前置注入 (prepend)
    for field, prefix in (patch_spec.get("prepend") or {}).items():
        current = str(target.get(field) or "").strip()
        prefix_str = str(prefix).strip()
        if prefix_str and prefix_str not in current:
            target[field] = f"{prefix_str}\n\n{current}" if current else prefix_str

    # 4. 追加注入 (append)
    for field, suffix in (patch_spec.get("append") or {}).items():
        current = str(target.get(field) or "").strip()
        suffix_str = str(suffix).strip()
        if suffix_str and suffix_str not in current:
            target[field] = f"{current}\n\n{suffix_str}" if current else suffix_str

    return payload


def load_card_payloads(source: Path) -> list[dict]:
    ext = source.suffix.lower()
    if ext == ".png":
        return read_png_card_payloads(str(source))
    if ext == ".json":
        with source.open("r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        _validate_card_object(raw)
        return [raw]
    raise ValueError(f"不支持的文件格式: {ext}，仅支持 .png 和 .json")


def save_card_payloads(source: Path, payloads: list[dict], output: Path) -> None:
    ext = output.suffix.lower()
    if ext == ".png":
        write_png_card_payloads(str(source), payloads, str(output))
    elif ext == ".json":
        with output.open("w", encoding="utf-8") as f:
            json.dump(payloads[0], f, ensure_ascii=False, indent=2)
            f.write("\n")
    else:
        raise ValueError(f"不支持的输出格式: {ext}")


def inspect_card(payload: dict) -> dict:
    data = payload.get("data", payload)
    char_ns = SimpleNamespace(
        name=data.get("name", "AI"),
        mes_example=data.get("mes_example", ""),
    )
    compiled_examples = compile_dialogue_examples(char_ns, "用户")
    user_count = sum(1 for m in compiled_examples if m["role"] == "user")
    assistant_count = sum(1 for m in compiled_examples if m["role"] == "assistant")
    return {
        "name": data.get("name", ""),
        "system_prompt_len": len(data.get("system_prompt") or data.get("system_prompt_override") or ""),
        "post_history_len": len(data.get("post_history_instructions") or ""),
        "mes_example_len": len(data.get("mes_example") or ""),
        "compiled_example_messages": len(compiled_examples),
        "compiled_user_examples": user_count,
        "compiled_assistant_examples": assistant_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="输入角色卡路径 (.png 或 .json)")
    parser.add_argument("--patch", type=Path, help="修缮规则 JSON 文件路径")
    parser.add_argument("--output", type=Path, help="输出文件路径")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="直接就地更新源角色卡文件",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="输出修缮前后的角色卡摘要与组装期 Few-shot 解析统计",
    )
    args = parser.parse_args()

    payloads = load_card_payloads(args.source)
    before_summary = inspect_card(payloads[0])

    if args.patch:
        if not args.in_place and not args.output:
            parser.error("执行修改时必须指定 --in-place 或 --output <路径>。")
        with args.patch.open("r", encoding="utf-8-sig") as f:
            patch_spec = json.load(f)
        target_path = args.source if args.in_place else args.output
        patched_payloads = [apply_patch_spec(p, patch_spec) for p in payloads]
        save_card_payloads(args.source, patched_payloads, target_path)
        after_summary = inspect_card(patched_payloads[0])
        if args.inspect:
            print(
                json.dumps(
                    {"before": before_summary, "after": after_summary, "output": str(target_path)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
    else:
        print(json.dumps(before_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
