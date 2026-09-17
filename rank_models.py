#!/usr/bin/env python3
"""
任务 B 辅助脚本：从 test_results.json 的可用模型中，结合公开评分榜单挑选高分模型
榜单源（web_extract 可抓取的页面）:
  1. Artificial Analysis Intelligence Index (benchlm.ai 镜像) - 模型名 + 百分比分数
  2. LMArena Text Arena (lmarena.ai/leaderboard/text) - 模型名 + ELO 分数

用法:
  1) 先用 web_extract 抓两个榜单页面，保存为两个 md 文件:
     python3 rank_models.py --fetch   # 可选：尝试直接抓取
  2) python3 rank_models.py --pick <arena_md> <aa_md> [--top N] [--min-score 30]
     # 输出: 每厂商按平均分排序的前 N 个模型 (default top=9)
"""
import json
import re
import sys


def parse_lmarena(path):
    """解析 LMArena md 文本，返回 {归一化模型名: elo}"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    scores = {}
    # 行格式: | rank | org | model ... | elo±x | votes | ...
    for line in text.splitlines():
        m = re.search(r"\[([a-zA-Z0-9][\w.+-]*[a-zA-Z0-9])\]\s*\(.*?\).*?\|\s*(\d{3,4})[±]", line)
        if not m:
            continue
        model, elo = m.group(1), int(m.group(2))
        key = norm(model)
        if key and (key not in scores or elo > scores[key]):
            scores[key] = elo
    return scores


def parse_aa(path):
    """解析 AA Intelligence Index md 文本，返回 {归一化模型名: 百分比分数}
    兼容两种格式:
      A) | 1 | [GPT-5.6 Sol](/models/gpt-5-6-sol)OpenAI · Closed | 58.9% |
      B) [GPT-5.6 Sol](/models/gpt-5-6-sol)OpenAI · Closed\n58.9%   (模型行与分数行分离)
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    scores = {}
    lines = text.splitlines()
    # 先试格式 A: 同行含模型和分数
    for line in lines:
        m = re.search(r"\[\s*([^\]]+?)\s*\]\([^)]*\)[^|\n]*\|\s*([\d.]+)\s*%", line)
        if m:
            key = norm(m.group(1))
            val = float(m.group(2))
            if key and (key not in scores or val > scores[key]):
                scores[key] = val
    # 再试格式 B: 模型行(无%)后紧跟分数行（中间可能有空行）
    for i, line in enumerate(lines):
        m = re.search(r"\[\s*([^\]]+?)\s*\]\([^)]*\)[^|\n]*\|\s*([\d.]+)\s*%", line)
        if m:
            continue  # 已在格式A处理
        m2 = re.search(r"\[\s*([^\]]+?)\s*\]\([^)]*\)\s*[^\d|]*$", line)
        if not m2:
            continue
        key = norm(m2.group(1))
        if not key or key in scores:
            continue
        # 向后找最近的非空行，若为纯分数则匹配
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            continue
        nxt = lines[j].strip()
        nm = re.match(r"^([\d.]+)\s*%?$", nxt)
        if nm:
            val = float(nm.group(1))
            if key not in scores or val > scores[key]:
                scores[key] = val
    return scores


def norm(name):
    """归一化模型名用于模糊匹配"""
    s = name.lower().strip()
    s = re.sub(r":free$", "", s)
    s = re.sub(r":cheap.*$", "", s)
    s = re.sub(r"^open/", "", s)
    s = re.sub(r"^composite/", "", s)
    s = re.sub(r"^[a-z-]+/", "", s)  # 去掉厂商前缀 (org/model)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def pick_top(results, arena, aa, top=9, min_score=0.0):
    """对每个厂商，从可用模型中挑选综合评分前 top 个"""
    out = {}
    for r in results:
        if not r.get("usable_models"):
            continue
        name = r["name"]
        scored = []
        for model in r["usable_models"]:
            key = norm(model)
            a = arena.get(key)
            b = aa.get(key)
            if a is None and b is None:
                continue
            # 有任一榜单分数才算；取平均（ELO 转 0-100 近似：(elo-1000)/5 ）
            vals = []
            if a is not None:
                vals.append(a)
            if b is not None:
                vals.append(b * 5.0 + 1000)  # 将 % 分数近似映射到 ELO 量纲
            avg = sum(vals) / len(vals)
            if avg < min_score:
                continue
            scored.append((avg, model, a, b))
        scored.sort(key=lambda x: -x[0])
        if scored:
            out[name] = scored[:top]
        else:
            # 榜单匹配不到该厂商模型（名字太特殊），兜底保留原可用模型（最多 top 个）
            out[name] = [(0.0, m, None, None) for m in r["usable_models"][:top]]
    return out


def find_cached(keyword):
    """在 web_extract 缓存目录中找最新的匹配榜单文件"""
    import glob
    import os
    patterns = [
        f"/home/amos/.hermes/cache/web/{keyword}*.md",
        f"/home/amos/.hermes/cache/web/*{keyword}*.md",
    ]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = [f for f in files if os.path.getsize(f) > 5000]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    if "--fetch" in sys.argv:
        print("请用 web_extract 抓取榜单页面后调用 --pick 或 --auto")
        return
    auto = "--auto" in sys.argv
    if "--pick" in sys.argv or auto:
        if auto:
            arena_md = find_cached("lmarena")
            aa_md = find_cached("benchlm")
            if not arena_md or not aa_md:
                print(f"[error] 未找到榜单缓存文件 (lmarena={arena_md}, benchlm={aa_md})", file=sys.stderr)
                print("请先用 web_extract 抓取 lmarena.ai/leaderboard/text 和 benchlm.ai/benchmarks/artificialanalysis", file=sys.stderr)
                sys.exit(1)
            print(f"[info] 缓存榜单: {arena_md}, {aa_md}", file=sys.stderr)
        else:
            i = sys.argv.index("--pick")
            arena_md = sys.argv[i + 1]
            aa_md = sys.argv[i + 2]
        top = 9
        if "--top" in sys.argv:
            top = int(sys.argv[sys.argv.index("--top") + 1])
        arena = parse_lmarena(arena_md)
        aa = parse_aa(aa_md)
        print(f"[info] LMArena 解析 {len(arena)} 个模型, AA 解析 {len(aa)} 个模型", file=sys.stderr)
        results = json.load(open("test_results.json", encoding="utf-8"))
        picked = pick_top(results, arena, aa, top=top)
        out = {}
        for name, rows in picked.items():
            out[name] = [
                {"model": m, "avg": round(a, 1), "lmarena_elo": x, "aa_pct": y}
                for a, m, x, y in rows
            ]
            print(f"{name}: {', '.join(m for _, m, _, _ in rows[:5])} ...", flush=True)
        with open("ranked_models.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("已保存 ranked_models.json", flush=True)


if __name__ == "__main__":
    main()
