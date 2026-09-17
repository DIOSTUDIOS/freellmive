#!/usr/bin/env python3
"""根据 test_results.json 更新 README 可用模型列（保留现有链接与行结构）"""
import json
import re
import openpyxl

# 1. 读取 xlsx 获取 厂商名 -> (官网地址, base_url)
wb = openpyxl.load_workbook('/data/project/freellmive/配置记录.xlsx')
ws = wb.active
rows = list(ws.iter_rows(values_only=True))[1:]
info_map = {}
for r in rows:
    if not r[1]:
        continue
    name = str(r[1]).strip()
    website = str(r[2]).strip() if r[2] else ''
    # URL & KEY 列第一行为 base_url
    base = ''
    if r[3]:
        first_line = str(r[3]).split('\n')[0].strip()
        if first_line.startswith('http'):
            base = first_line.replace('https://', '').replace('http://', '').rstrip('/')
    info_map[name] = (website, base)
# SiliconFlow 的 xlsx base_url 是坏数据，补真实地址
if 'SiliconFlow' in info_map:
    info_map['SiliconFlow'] = (info_map['SiliconFlow'][0], 'api.siliconflow.cn/v1')

# 手动补全：xlsx 无 base_url 但已查证官方 OpenAI 兼容端点的厂商
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
        # 只取前 15 个，超出部分用 +N
        if len(models) > 15:
            shown = ', '.join(models[:15]) + f' 等共 {len(models)} 个'
        else:
            shown = ', '.join(models)
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
