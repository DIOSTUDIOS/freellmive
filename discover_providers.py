#!/usr/bin/env python3
"""
任务 A 辅助脚本：验证候选厂商官网可达性，生成待加入 README 的新行
用法:
  echo "https://example.com/|厂商名" | python3 discover_providers.py --check
  或 python3 discover_providers.py --check  # 从 providers_candidates.txt 读取
输出: 可达的候选列表 (名称|官网URL)
"""
import sys
import urllib.request
import urllib.error
import socket
import ssl
import time

TIMEOUT = 15
CANDIDATES_FILE = "providers_candidates.txt"


def check_url(url):
    """检查 URL 是否可达（国内网络）。返回 (ok, status_or_err)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LLM-provider-scout/1.0)"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return resp.status < 500, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        # 401/403/404 都算"可达"（服务器有响应，只是页面需要权限或路径不对）
        if e.code in (401, 403, 404, 405):
            return True, f"HTTP {e.code}"
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, socket.gaierror, ConnectionError, TimeoutError) as e:
        return False, str(e)[:80]


def main():
    if "--check" not in sys.argv:
        print(__doc__)
        return
    candidates = []
    try:
        with open(CANDIDATES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "|" in line:
                    url, name = line.split("|", 1)
                    candidates.append((url.strip(), name.strip()))
                else:
                    candidates.append((line, ""))
    except FileNotFoundError:
        print("未找到 candidates 文件，从 stdin 读取 (每行: url|名称)")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                url, name = line.split("|", 1)
            else:
                url, name = line, ""
            candidates.append((url.strip(), name.strip()))

    ok_list = []
    for url, name in candidates:
        ok, info = check_url(url)
        status = "OK " if ok else "FAIL"
        print(f"{status} {url} [{info}] {name}", flush=True)
        if ok:
            ok_list.append((name, url))
        time.sleep(1)

    print("\n===== 可达候选 =====")
    for name, url in ok_list:
        print(f"{name or url} | {url}")


if __name__ == "__main__":
    main()
