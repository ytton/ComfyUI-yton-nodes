"""Add a shared second-pass switch to the organized H3 workflow."""

import copy
import json
from pathlib import Path
import sys
import uuid


def add_switch(data):
    hosts = {n['properties'].get('h3_layout_module'): n for n in data['nodes']}
    definitions = {s['id']: s for s in data['definitions']['subgraphs']}
    last_node = max(data['last_node_id'], *(s['state']['lastNodeId'] for s in definitions.values()))
    last_link = max(data['last_link_id'], *(s['state']['lastLinkId'] for s in definitions.values()))

    def link(graph, source, output, target, slot, kind):
        nonlocal last_link
        last_link += 1
        graph['links'].append([last_link, source, output, target, slot, kind] if graph is data else {
            'id': last_link, 'origin_id': source, 'origin_slot': output,
            'target_id': target, 'target_slot': slot, 'type': kind})
        return last_link

    def identity(node, key):
        nonlocal last_node
        last_node += 1
        node['id'] = last_node
        node['properties'] = {'Node name for S&R': node['type'], 'h3_layout_key': str(last_node),
                              'h3_layout_module': key}
        return node

    switch = identity({'type': 'PrimitiveBoolean', 'pos': [1130, 1570], 'size': [330, 80],
        'flags': {}, 'order': 0, 'mode': 0, 'title': '启用二采 · 关闭使用最终分辨率直采',
        'inputs': [{'name': 'value', 'type': 'BOOLEAN', 'widget': {'name': 'value'}, 'link': None}],
        'outputs': [{'name': 'BOOLEAN', 'type': 'BOOLEAN', 'links': []}],
        'widgets_values': [True], 'widgets_values_named': {'value': True}, 'color': '#232', 'bgcolor': '#353'}, 'second_pass_switch')
    data['nodes'].append(switch)
    branch_template = next(n for n in definitions[hosts['conditions']['type']]['nodes'] if n['id'] == 633)

    def enable_input(key, targets):
        host = hosts[key]
        graph = definitions[host['type']]
        slot = len(graph['inputs'])
        graph['inputs'].append({'id': str(uuid.uuid4()), 'name': 'enable_second_pass',
            'label': '启用二采', 'type': 'BOOLEAN', 'linkIds': [], 'pos': [276, 174 + slot * 24]})
        host['inputs'].append({'name': 'enable_second_pass', 'label': '启用二采', 'type': 'BOOLEAN', 'link': None})
        link(data, switch['id'], 0, host['id'], slot, 'BOOLEAN')
        for target, name in targets:
            target_slot = next(i for i, p in enumerate(target['inputs']) if p['name'] == name)
            link(graph, -10, slot, target['id'], target_slot, 'BOOLEAN')

    def branch(graph, title, pos, true_source, false_source, kind):
        node = identity(copy.deepcopy(branch_template), title)
        node.update(title=title, pos=pos, size=[440, 140])
        node['widgets_values'] = [True]
        node['widgets_values_named'] = {'cond': True}
        graph['nodes'].append(node)
        link(graph, *true_source, node['id'], 0, kind)
        link(graph, *false_source, node['id'], 1, kind)
        return node

    size = definitions[hosts['size']['type']]
    expressions = [n for n in size['nodes'] if n['id'] in (602, 603)]
    for node in expressions:
        expression = 'max(32, floor(a * b / 32) * 32) if c else a'
        node['widgets_values'] = [expression]
        node['widgets_values_named'] = {'expression': expression}
        node['title'] = '首采宽度 · 二采缩放 / 单采原宽' if node['id'] == 602 else '首采高度 · 二采缩放 / 单采原高'
    enable_input('size', [(n, 'values.c') for n in expressions])
    size['name'] = '首采尺寸 · 单采使用最终宽高'
    hosts['size'].update(pos=[1130, 1810], size=[330, 175], title=size['name'])
    hosts['scale'].update(pos=[1130, 1670], size=[330, 100], title='首采比例 · 仅启用二采时生效')

    conditions = definitions[hosts['conditions']['type']]
    signal = branch(conditions, '编码等待 · 单采只等待首采条件', [400, 1610], (633, 0), (631, 0), 'CONDITIONING')
    next(n for n in conditions['nodes'] if n['id'] == 622).update(pos=[960, 1610], title='等待当前模式所需的参考编码')
    next(n for n in conditions['nodes'] if n['id'] == 623)['pos'] = [1520, 1610]
    next(l for l in conditions['links'] if l['id'] == 1774)['origin_id'] = signal['id']
    enable_input('conditions', [(signal, 'cond')])
    next(n for n in conditions['nodes'] if n['id'] == 620)['widgets_values'] = [
        '# 编码后释放 TE\n\n二采开启时等待两套参考与上下文编码；关闭时只执行首采编码。随后释放 TE，再进入采样。\n\n循环传递最终 VIDEO，包含修脸、裁重叠和颜色匹配后的画面与音频。']

    second = definitions[hosts['second']['type']]
    latent = branch(second, '采样结果 · 二采 / 一采直出', [2080, 800], (617, 1), (-10, 0), 'LATENT')
    model = branch(second, '修脸模型 · 二采模型 / 主模型', [2080, 530], (612, 0), (-10, 3), 'MODEL')
    second['outputNode']['bounding'][0] = 2670
    next(l for l in second['links'] if l['id'] == 1700).update(origin_id=latent['id'], origin_slot=0)
    next(l for l in second['links'] if l['id'] == 1770).update(origin_id=model['id'], origin_slot=0)
    enable_input('second', [(latent, 'cond'), (model, 'cond')])
    second['name'] = '05 传统二采 · 可关闭直出'
    second['outputs'][1]['label'] = '最终 AV Latent'
    hosts['second']['outputs'][1]['label'] = '最终 AV Latent'
    next(n for n in second['nodes'] if n['id'] == 621)['widgets_values'] = [
        '# 传统二采与单采直出\n\n启用二采：传统 3D Latent 放大 → SA Solver；Sigma：0.631578922 → 0.3158 → 0，共 2 步。\n\n关闭二采：直接输出首采 AV Latent，跳过放大、二采采样与二采模型分块；后方修脸使用主模型。首采尺寸由总开关切换为最终宽高。']

    for host_id in (643, 644):
        host = next(n for n in data['nodes'] if n['id'] == host_id)
        next(p for p in host['inputs'] if p['name'] == 'samples')['label'] = '最终 AV Latent'
        next(p for p in definitions[host['type']]['inputs'] if p['name'] == 'samples')['label'] = '最终 AV Latent'
    note = next(n for n in data['nodes'] if n['id'] == 619)
    note['widgets_values'][0] += '\n\n【启用二采】位于最终分辨率下方。开启时使用首采比例；关闭时忽略该比例，一采直接按最终分辨率生成，跳过二采编码、放大和二采采样。小脸修复仍由其自身开关控制。'

    def sync(graph):
        nodes = {n['id']: n for n in graph['nodes']}
        for n in nodes.values():
            if n['type'] == 'MarkdownNote':
                n['widgets_values_named'] = {'text': n['widgets_values'][0]}
            for p in n.get('inputs', []):
                p['link'] = None
            for p in n.get('outputs', []):
                p['links'] = []
        for p in [*graph.get('inputs', []), *graph.get('outputs', [])]:
            p['linkIds'] = []
        for item in graph['links']:
            lid, source, output, target, slot = item[:5] if isinstance(item, list) else (
                item['id'], item['origin_id'], item['origin_slot'], item['target_id'], item['target_slot'])
            if source == -10:
                graph['inputs'][output]['linkIds'].append(lid)
            else:
                nodes[source]['outputs'][output]['links'].append(lid)
            if target == -20:
                graph['outputs'][slot]['linkIds'].append(lid)
            else:
                nodes[target]['inputs'][slot]['link'] = lid

    for graph in [data, *definitions.values()]:
        sync(graph)
        if graph is not data:
            graph['state'].update(lastNodeId=last_node, lastLinkId=last_link)
    data.update(last_node_id=last_node, last_link_id=last_link)
    return data


if __name__ == '__main__':
    for filename in sys.argv[1:]:
        path = Path(filename)
        workflow = add_switch(json.loads(path.read_text('utf-8')))
        path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        print(path)
