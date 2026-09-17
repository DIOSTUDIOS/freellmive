from openai import OpenAI
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

CONFIG_FILE = "providers_config.json"
RESULT_FILE = "test_results.json"
TIMEOUT = 25
PROVIDER_WORKERS = 6   # 厂商级并发
MODEL_WORKERS = 2      # 每个厂商内部模型并发

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def build_client(base_url, api_key):
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=TIMEOUT,
        max_retries=0,
    )


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_provider(name, cfg, prior_models=None):
    """测试单个厂商：列出模型 -> 逐个真实对话 -> 返回可用模型列表"""
    base_url = cfg["base_url"]
    api_keys = cfg["api_keys"]
    if not base_url or not api_keys:
        return {"name": name, "base_url": base_url, "usable_models": [], "error": "no config"}

    # 依次尝试多个 key，建一个 client 并列出模型
    client = None
    model_ids = []
    list_error = None
    for key in api_keys:
        try:
            client = build_client(base_url, key)
            models = client.models.list()
            model_ids = [m.id for m in models]
            break
        except Exception as e:
            list_error = str(e)[:120]
            continue
    if client is None:
        return {"name": name, "base_url": base_url, "usable_models": [], "error": list_error or "no client"}
    if not model_ids:
        # /models 不可用或为空，尝试用 prior_models 直接测
        if prior_models:
            model_ids = prior_models
        else:
            return {"name": name, "base_url": base_url, "usable_models": [], "error": list_error or "no models listed"}

    # 全量测试所有模型（README 已有模型优先）
    queue = []
    if prior_models:
        for m in prior_models:
            if m in model_ids and m not in queue:
                queue.append(m)
    for m in model_ids:
        if m not in queue:
            queue.append(m)

    def _test_one(model):
        # 依次用所有 key 尝试
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
        return None

    usable = []
    with ThreadPoolExecutor(max_workers=MODEL_WORKERS) as pool:
        futures = {pool.submit(_test_one, m): m for m in queue}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                usable.append(r)
            done += 1
            if done % 20 == 0 or done == len(queue):
                log(f"  [{name}] 进度 {done}/{len(queue)}，已可用 {len(usable)}")

    try:
        client.close()
    except Exception:
        pass

    return {
        "name": name,
        "base_url": base_url,
        "usable_models": usable,
        "error": None,
    }


def main():
    config = load_config()
    # 合并已有结果，只测缺失的厂商
    try:
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            results = json.load(f)
        done_names = {r["name"] for r in results}
    except Exception:
        results = []
        done_names = set()
    config = {k: v for k, v in config.items() if k not in done_names}
    if not config:
        print("所有厂商均已测试完成", flush=True)
        return
    try:
        with open("README.md", "r", encoding="utf-8") as f:
            readme_text = f.read()
        prior_models = re.findall(r"`([^`]+)`", readme_text)
    except Exception:
        prior_models = []

    with ThreadPoolExecutor(max_workers=PROVIDER_WORKERS) as executor:
        futures = {
            executor.submit(test_provider, name, cfg, prior_models): name
            for name, cfg in config.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                res = future.result()
                results.append(res)
                log(f"[{'OK' if res['usable_models'] else 'FAIL'}] {name}: {len(res['usable_models'])} 个可用模型")
                if res["error"]:
                    log(f"      error: {res['error']}")
            except Exception as e:
                results.append({"name": name, "usable_models": [], "error": str(e)[:120]})
                log(f"[ERROR] {name}: {str(e)[:120]}")
            # 增量保存，防止中途崩溃丢数据
            results.sort(key=lambda x: x["name"])
            try:
                with open(RESULT_FILE, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log(f"[WARN] 保存结果失败: {str(e)[:80]}")

    print("\n===== 测试完成 =====", flush=True)
    for r in results:
        if r["usable_models"]:
            print(f"{r['name']}: {', '.join(r['usable_models'])}", flush=True)


if __name__ == "__main__":
    main()
