"""无损导出 PNG 的所有 chara JSON，不执行展示字段清洗，也不连接数据库。"""

import argparse
import json
from pathlib import Path

from services.parse import read_png_card_payloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="输出文件夹；已有文件不覆盖")
    args = parser.parse_args()
    cards = read_png_card_payloads(str(args.source))
    args.output.mkdir(parents=True, exist_ok=True)
    paths = [args.output / f"{args.source.stem}.chara-{i + 1}.json" for i in range(len(cards))]
    if any(path.exists() for path in paths):
        parser.error("输出 JSON 已存在，请更换目录或移走旧文件。")
    for path, card in zip(paths, cards):
        with path.open("x", encoding="utf-8") as output:
            json.dump(card, output, ensure_ascii=False, indent=2)
            output.write("\n")
        print(path)


if __name__ == "__main__":
    main()
