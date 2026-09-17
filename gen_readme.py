#!/usr/bin/env python3
"""根据 test_results.json 更新 README 可用模型列（保留现有链接与行结构）"""
import json
import re

# 1. 读取当前 README 表格行，提取 厂商名 -> (官网地址, base_url)
with open('/data/project/freellmive/README.md', 'r', encoding='utf-8') as f:
    readme = f.read()
table_start = readme.find('| 厂商名称')
table_end = readme.find('\n\n', table_start)
table_text = readme[table_start:table_end]

info_map = {}
row_pattern = re.compile(r'\|\s*\[(.*?)\]\((.*?)\)\s*\|\s*`?([^`|]*)`?\s*\|\s*.*?\|')
for line in table_text.split('\n'):
    line = line.strip()
    if not line.startswith('| ['):
        continue
    m = row_pattern.match(line)
    if not m:
        continue
    name, website, base = m.groups()
    info_map[name.strip()] = (website.strip(), base.strip())

# SiliconFlow 的 base_url 补真实地址（xlsx 中为坏数据）
if 'SiliconFlow' in info_map:
    info_map['SiliconFlow'] = (info_map['SiliconFlow'][0], 'api.siliconflow.cn/v1')

# 手动补全：查证官方 OpenAI 兼容端点的厂商
BASE_URL_FIX = {
    'Speechify': 'api.sws.speechify.com/v1',
    'BlazeAPI': 'api.blazeapi.org/free/v1',
    'Lucidity': 'composite.lucidity.sh/v1',
    'Api.Airforce': 'api.airforce/v1',
    'DreamPrompting': 'dreamprompting.com/api/v1',
    'Waterfall': 'api.getwaterfall.org/v1',
    'Cohere': 'api.cohere.com/v1',
    'AINative Studio': 'api.ainative.studio/v1',
    'NaraRouter': 'router.bynara.id/v1',
    'Volcengine Ark': 'ark.cn-beijing.volces.com/api/v3',
    'iFlytek Spark': 'spark-api-open.xf-yun.com/v1',
}
for name, base in BASE_URL_FIX.items():
    if name in info_map:
        info_map[name] = (info_map[name][0], base)

# 2. 读取测试结果
results = json.load(open('/data/project/freellmive/test_results.json'))
usable_map = {}
for r in results:
    if r.get('usable_models'):
        usable_map[r['name']] = r['usable_models']

# 3. 读取当前 README，保留非表格部分与表头，重建表格行
with open('/data/project/freellmive/README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

# 提取表格区域前后的文本
table_start = readme.find('| 厂商名称')
table_end = readme.find('\n\n', table_start)
header_part = readme[:table_start]
footer_part = readme[table_end:]

# 提取现有行（厂商名 + 链接）
lines = readme[table_start:table_end].split('\n')
header = "| 厂商名称 | Base URL | 可用模型 |"
sep = "|---------|----------|---------|"
new_rows = [header, sep]
name_pattern = re.compile(r'\| \[(.*?)\]\((.*?)\) \| (.*?) \| (.*?) \|')

for line in lines[2:]:
    line = line.strip()
    if not line:
        continue
    m = name_pattern.match(line)
    if not m:
        continue
    name, url, _, _ = m.groups()
    website, base = info_map.get(name, (url, ''))
    models = usable_map.get(name, [])
    if models:
        # 每个模型占一行（GitHub 表格支持 <br> 换行）
        shown = '<br>'.join(models)
    else:
        shown = '—'
    if base and base != '—':
        new_rows.append(f'| [{name}]({url}) | `{base}` | {shown} |')
    else:
        new_rows.append(f'| [{name}]({url}) | — | {shown} |')

new_table = '\n'.join(new_rows)

new_readme = header_part + new_table + footer_part

with open('/data/project/freellmive/README.md', 'w', encoding='utf-8') as f:
    f.write(new_readme)

print('README 已更新')
print('有可用模型的厂商:', len(usable_map))
