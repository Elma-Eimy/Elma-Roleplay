"""检查 Git 跟踪 Markdown 中的本地文件链接，不访问网络或导入应用。"""

from pathlib import Path
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


INLINE_LINK = re.compile(
    r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|(?:\\.|[^\s()])+(?:\([^()\n]*\)(?:\\.|[^\s()])*)*)'
)
REFERENCE = re.compile(r'^ {0,3}\[([^\]\n]+)\]:\s*(<[^>\n]+>|\S+)', re.MULTILINE)
REFERENCE_USE = re.compile(r'!?\[([^\]\n]+)\](?:\[([^\]\n]*)\])?')


def prose_only(content):
    """排除围栏、缩进代码块和行内代码中的示例链接。"""
    fence = None
    lines = []
    for line in content.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            lines.append("")
        elif marker:
            fence = marker[1]
            lines.append("")
        elif line.startswith(("    ", "\t")):
            lines.append("")
        else:
            lines.append(line)
    return re.sub(r'(`+)[\s\S]*?\1(?!`)', lambda m: "\n" * m[0].count("\n"), "\n".join(lines))


def link_targets(content):
    """读取常见行内链接和引用式链接；不解析 HTML 或完整 Markdown 语法。"""
    prose = prose_only(content)
    for match in INLINE_LINK.finditer(prose):
        yield prose.count("\n", 0, match.start()) + 1, match[1].strip("<>")
    definitions = {
        " ".join(match[1].casefold().split()): match[2].strip("<>")
        for match in REFERENCE.finditer(prose)
    }
    # 声明和行内链接不是引用使用点，保留行号后再扫描引用。
    prose = REFERENCE.sub(lambda m: re.sub(r'[^\n]', ' ', m[0]), prose)
    prose = INLINE_LINK.sub(lambda m: re.sub(r'[^\n]', ' ', m[0]), prose)
    for match in REFERENCE_USE.finditer(prose):
        label = match[2] or match[1]
        target = definitions.get(" ".join(label.casefold().split()))
        if target is not None:
            yield prose.count("\n", 0, match.start()) + 1, target


def check_repository(root):
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode("utf-8").split("\0")) - {""}
    directories = set()
    for name in tracked:
        parent = posixpath.dirname(name)
        while parent:
            directories.add(parent)
            parent = posixpath.dirname(parent)
    valid = tracked | directories | {"."}
    folded = {name.casefold(): name for name in valid}
    errors = []
    count = 0
    for name in sorted(tracked):
        source = root / name
        if source.suffix.lower() != ".md" or not source.is_file() or source.is_symlink():
            continue
        count += 1
        for line, target in link_targets(source.read_text(encoding="utf-8-sig")):
            target = re.sub(r'\\([\\()<> ])', r'\1', target)
            try:
                url = urlsplit(target)
            except ValueError:
                errors.append(f"{name}:{line}: 无法解析链接 {target}")
                continue
            if url.scheme or url.netloc or not url.path:
                continue
            path = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(url.path)))
            if path not in valid:
                correct = folded.get(path.casefold())
                reason = f"路径大小写不符，应指向 {correct}" if correct else "目标不在 Git 跟踪文件或目录中"
                errors.append(f"{name}:{line}: {target}：{reason}")
            elif not (root / path).exists():
                errors.append(f"{name}:{line}: {target}：目标已从工作区删除")
    return count, errors


def main():
    root = Path(__file__).resolve().parents[1]
    count, errors = check_repository(root)
    for error in errors:
        print(error, file=sys.stderr)
    print(f"文档链接检查：{count} 个 Git 跟踪 Markdown 文件，{len(errors)} 个错误。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
