#!/usr/bin/env python3
"""
任务 B 辅助脚本：只重测「上次可用」的模型
- 读取 providers_config.json（有 key 的厂商）+ test_results.json（上次可用模型）
- 对每个有 key 的厂商，重测上次 usable_models 中的模型（厂商可能调整）
- 也扫描模型列表，若上次可用模型已不在列表中则标记 removed
- 更新 test_results.json（增量保存）
用法: python3 retest_usable.py [--provider 厂商名]
"""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

CONFIG_FILE = "providers_config.json"
RESULT_FILE = "test_results.json"
TIMEOUT = 25
PROVIDER_WORKERS = 4   # 厂商级并发（照顾限流）
MODEL_WORKERS = 2
NEW_PROBE_LIMIT = 20   # 新厂商探测的模型数上限

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def build_client(base_url, api_key):
    return OpenAI(base_url=base_url, api_key=api_key, timeout=TIMEOUT, max_retries=0)


def retest_provider(name, cfg, prev_usable, mode="retest"):
    """重测该厂商上次可用的模型，返回 (still_usable, removed, ...)
    mode="retest": 只测 prev_usable（默认）
    mode="new":    新厂商，探测前 NEW_PROBE_LIMIT 个模型
    """
    base_url = cfg["base_url"]
    api_keys = cfg["api_keys"]
    if not base_url or not api_keys:
        return {"name": name, "usable_models": [], "error": "no config",
                "removed": list(prev_usable), "newly": []}

    # 建立 client 并列出当前模型集合
    client = None
    current_ids = set()
    list_error = None
    for key in api_keys:
        try:
            client = build_client(base_url, key)
            models = client.models.list()
            current_ids = {m.id for m in models}
            break
        except Exception as e:
            list_error = str(e)[:120]
            continue
    if client is None:
        return {"name": name, "usable_models": [], "error": list_error or "no client",
                "removed": list(prev_usable), "newly": []}

    if mode == "new":
        removed = []
        queue = sorted(current_ids)[:NEW_PROBE_LIMIT]
    else:
        # 重测队列 = 上次可用 ∩ 当前列表（不在当前列表 => removed）
        removed = [m for m in prev_usable if m not in current_ids]
        queue = [m for m in prev_usable if m in current_ids]

    def _test_one(model):
        import time as _t
        # 失败后间隔重试一轮，减少限流导致的误判
        for attempt in range(2):
            for ki in range(len(api_keys)):
                try:
                    c = client if ki == 0 else build_client(base_url, api_keys[ki])
                    resp = c.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": "你好，请用一句话介绍一下你自己。"}],
                        max_tokens=200,
                    )
                    if resp.choices and resp.choices[0].message.content:
                        return model
                except Exception:
                    continue
            if attempt == 0:
                _t.sleep(3)
        return None

    usable = []
    if queue:
        with ThreadPoolExecutor(max_workers=MODEL_WORKERS) as pool:
            futures = {pool.submit(_test_one, m): m for m in queue}
            for fut in as_completed(futures):
                r = fut.result()
                if r:
                    usable.append(r)
    try:
        client.close()
    except Exception:
        pass

    return {
        "name": name,
        "usable_models": usable,
        "error": None,
        "removed": removed,
        "newly": [],  # 新模型由全量发现，本脚本不扫描全列表
    }


def main():
    config = json.load(open(CONFIG_FILE, encoding="utf-8"))
    try:
        results = json.load(open(RESULT_FILE, encoding="utf-8"))
    except Exception:
        results = []

    # 只处理有 key 的厂商
    todo = {name: cfg for name, cfg in config.items() if cfg.get("api_keys") and cfg.get("base_url")}

    # 上次可用模型映射
    prev_map = {}
    for r in results:
        if r.get("usable_models"):
            prev_map[r["name"]] = r["usable_models"]

    known_names = {r["name"] for r in results} if results else set()
    # 分类：有上次可用 => retest；全新厂商 => new；上次不可用 => 跳过（保留原诊断）
    plan = {}
    for name, cfg in todo.items():
        if name in prev_map:
            plan[name] = ("retest", prev_map[name])
        elif name not in known_names:
            plan[name] = ("new", [])
    skipped = [n for n in todo if n not in plan]

    # 过滤命令行指定厂商
    if "--provider" in sys.argv:
        i = sys.argv.index("--provider")
        only = sys.argv[i + 1]
        plan = {n: v for n, v in plan.items() if n == only}
    if not plan:
        print(f"没有需要重测的厂商。跳过 {len(skipped)} 个上次不可用的厂商（保留原诊断）", flush=True)
        return

    print(f"待重测 {len(plan)} 个厂商 | 跳过 {len(skipped)} 个上次不可用的", flush=True)

    results_map = {r["name"]: r for r in results}
    with ThreadPoolExecutor(max_workers=PROVIDER_WORKERS) as ex:
        futures = {ex.submit(retest_provider, name, todo[name], prev, mode): name
                   for name, (mode, prev) in plan.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"name": name, "usable_models": [], "error": str(e)[:120],
                       "removed": plan[name][1], "newly": []}
            # 合并回结果集
            entry = results_map.get(name, {"name": name, "base_url": config[name]["base_url"]})
            entry["base_url"] = config[name]["base_url"]
            entry["usable_models"] = res["usable_models"]
            entry["error"] = res["error"]
            if "removed" in res:
                entry["removed"] = res["removed"]
            results_map[name] = entry
            log(f"[{'OK' if res['usable_models'] else 'FAIL'}] {name} ({plan[name][0]}): 可用 {len(res['usable_models'])} | 失效 {len(res['removed'])}")
            if res["error"]:
                log(f"      error: {res['error']}")
            # 增量保存
            merged = list(results_map.values())
            merged.sort(key=lambda x: x["name"])
            with open(RESULT_FILE, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

    print("\n===== 重测完成 =====", flush=True)
    for name in sorted(results_map):
        r = results_map[name]
        if r.get("usable_models"):
            print(f"{name}: {', '.join(r['usable_models'][:8])}{'...' if len(r['usable_models'])>8 else ''}", flush=True)
        elif r.get("removed"):
            print(f"{name}: 上次 {len(r['removed'])} 个模型已全部失效", flush=True)


if __name__ == "__main__":
    main()
