#!/usr/bin/env python3
"""
从 git 历史的所有 README 版本恢复「历史上曾被列为可用」的模型名，
合并进 test_results.json 的 usable_models（作为待验证池）。
用途：修正限流误判导致模型被从池子中删除的问题。
"""
import json
import re
import subprocess

REPO = "/data/project/freellmive"
README = f"{REPO}/README.md"


def get_readme_versions():
    """取所有提交过的 README 版本内容"""
    revs = subprocess.run(
        ["git", "-C", REPO, "log", "--format=%H", "--", "README.md"],
        capture_output=True, text=True,
    ).stdout.split()
    versions = []
    for r in revs:
        out = subprocess.run(
            ["git", "-C", REPO, "show", f"{r}:README.md"],
            capture_output=True, text=True,
        ).stdout
        if out:
            versions.append(out)
    # 加上当前工作区版本
    with open(README, encoding="utf-8") as f:
        versions.append(f.read())
    return versions


def parse_rows(text):
    """从 README 表格提取 {厂商名: [模型,...]}"""
    result = {}
    pat = re.compile(r"\|\s*\[([^\]]+)\]\([^)]*\)\s*\|\s*`?([^`|]*)`?\s*\|\s*([^|]*)\|")
    for line in text.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        name, base, models_cell = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if not models_cell or models_cell in ("—", "-"):
            continue
        models = [x.strip() for x in re.split(r"<br>|,", models_cell) if x.strip() and x.strip() != "—"]
        # 去掉「等共 N 个」这类尾巴
        models = [x for x in models if not re.match(r"^等共\s*\d+\s*个$", x)]
        if models:
            result.setdefault(name, set()).update(models)
    return result


def main():
    pool = {}
    for text in get_readme_versions():
        for name, models in parse_rows(text).items():
            pool.setdefault(name, set()).update(models)

    with open(f"{REPO}/test_results.json", encoding="utf-8") as f:
        results = json.load(f)

    restored = {}
    for r in results:
        name = r["name"]
        hist = pool.get(name)
        if not hist:
            continue
        current = set(r.get("usable_models") or [])
        missing = hist - current
        if missing:
            restored[name] = sorted(missing)
            r["usable_models"] = sorted(current | missing)

    with open(f"{REPO}/test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"从历史 README 恢复模型到 {len(restored)} 个厂商的待验证池：")
    for name, models in sorted(restored.items()):
        print(f"  {name}: +{len(models)} 个  {', '.join(models[:5])}{'...' if len(models) > 5 else ''}")


if __name__ == "__main__":
    main()
