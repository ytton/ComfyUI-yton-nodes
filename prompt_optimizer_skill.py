"""Load a local multi-file Skill as context for one model request."""

import os
from pathlib import Path

from .prompt_optimizer import OptimizerError


MAX_SKILL_BYTES = 512 * 1024
MAX_SKILL_FILES = 64
TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml",
    ".csv", ".tsv", ".xml", ".html", ".css", ".jinja", ".jinja2", ".j2",
    ".py", ".js", ".ts", ".sh", ".ps1", ".sql",
}
SKIP_DIRECTORIES = {"node_modules", "__pycache__", "venv", "env"}
SKILLS_DIRECTORY = Path(__file__).resolve().parent / "skills"


def available_skills():
    if not SKILLS_DIRECTORY.exists():
        return []
    try:
        return sorted(path.name for path in SKILLS_DIRECTORY.iterdir()
                      if path.is_dir() and not path.name.startswith(".")
                      and (path / "SKILL.md").is_file()
                      and path.resolve().is_relative_to(SKILLS_DIRECTORY.resolve()))
    except OSError:
        raise OptimizerError("无法读取 Skill 列表，请检查插件 skills 目录的访问权限。") from None


def load_skill(name):
    if not isinstance(name, str):
        raise OptimizerError("请选择有效的 Skill。")
    if not name:
        return ""
    if name not in available_skills():
        raise OptimizerError("所选 Skill 不可用，请刷新列表后重新选择。")
    root = SKILLS_DIRECTORY / name
    try:
        root = root.resolve(strict=True)
        if not root.is_dir() or not (root / "SKILL.md").is_file():
            raise OptimizerError("Skill 目录根部需要包含 SKILL.md。")
        files = []

        def scan_error(error):
            raise error

        for parent, directories, names in os.walk(root, onerror=scan_error, followlinks=False):
            directories[:] = sorted(name for name in directories
                                    if not name.startswith(".") and name not in SKIP_DIRECTORIES
                                    and not (Path(parent) / name).is_symlink())
            for name in sorted(names):
                path = Path(parent) / name
                if name.startswith(".") or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if not path.resolve().is_relative_to(root):
                    raise OptimizerError(f"Skill 文件指向目录外部：{path.relative_to(root).as_posix()}")
                files.append(path)
                if len(files) > MAX_SKILL_FILES:
                    raise OptimizerError(f"Skill 文本文件超过 {MAX_SKILL_FILES} 个，请精简目录。")
        files.sort(key=lambda path: (path != root / "SKILL.md", path.relative_to(root).as_posix()))
        remaining = MAX_SKILL_BYTES
        sections = []
        for path in files:
            relative = path.relative_to(root).as_posix()
            with path.open("rb") as handle:
                raw = handle.read(remaining + 1)
            remaining -= len(raw)
            if remaining < 0:
                raise OptimizerError("Skill 文本总量超过 512 KiB，请精简参考文件。")
            try:
                text = raw.decode("utf-8-sig").strip()
            except UnicodeError:
                raise OptimizerError(f"Skill 文件需使用 UTF-8 文本编码：{relative}") from None
            if "\x00" in text:
                raise OptimizerError(f"Skill 文件包含二进制内容：{relative}")
            if path == root / "SKILL.md" and not text:
                raise OptimizerError("SKILL.md 内容不能为空。")
            if text:
                sections.append(f"### 文件：{relative}\n\n{text}")
        return "## Skill 文件包\n\n文件路径相对于 Skill 目录；源码文件作为参考文本阅读。\n\n" + "\n\n".join(sections)
    except OSError:
        raise OptimizerError("无法读取 Skill 目录，请检查路径和文件访问权限。") from None
