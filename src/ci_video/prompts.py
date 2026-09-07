"""Project-local immutable prompt versions, active pointers and literal variables."""
import json
import re
from pathlib import Path

from .storage import digest, now, read, save

DEFAULTS = Path(__file__).resolve().parents[2] / 'prompts'
IDS = ('research', 'script', 'image', 'tts')
PARAMETERS = {'research': {'model', 'temperature', 'max_tokens'},
              'script': {'model', 'temperature', 'max_tokens'},
              'image': {'model', 'size', 'quality'},
              'tts': {'model', 'voice', 'speed', 'edge_rate', 'edge_voice'}}


def folder(project, name):
    if name not in IDS:
        raise ValueError('Unknown prompt')
    return Path(project) / 'prompts' / name


def validate(data):
    name = data['id']
    if name not in IDS or not isinstance(data['body'], str) or not data['body'].strip():
        raise ValueError('Prompt 正文不能为空。')
    variables = sorted(set(re.findall(r'\{\{\s*([A-Za-z_]\w*)\s*\}\}', data['body'])))
    if set(variables) - ({'visual_intent'} if name == 'image' else set()):
        raise ValueError('当前仅生图模板支持 {{visual_intent}}；其他输入由阶段提供。')
    params = data.get('parameters', {})
    if not isinstance(params, dict) or set(params) - PARAMETERS[name]:
        raise ValueError(f'支持的参数：{", ".join(sorted(PARAMETERS[name]))}')
    for key, value in params.items():
        if key in {'temperature', 'speed', 'max_tokens'}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'{key} 必须为数值')
            limits = {'temperature': (0, 2), 'speed': (.25, 4), 'max_tokens': (1, 32000)}
            low, high = limits[key]
            if not low <= value <= high or (key == 'max_tokens' and int(value) != value):
                raise ValueError(f'{key} 超出有效范围')
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f'{key} 必须为非空文本')
        if key == 'edge_rate' and not re.fullmatch(r'[+-]\d+%', value):
            raise ValueError('edge_rate 示例：-35%')
    return {'id': name, 'name': str(data.get('name') or name), 'body': data['body'],
            'variables': variables, 'parameters': params}


def version(data, note=''):
    content = validate(data)
    revision = digest(json.dumps(content, sort_keys=True, ensure_ascii=False))[:20]
    return {**content, 'version': revision, 'created_at': now(), 'note': str(note)}


def active(project, name):
    root = folder(project, name)
    pointer = root / 'active.json'
    if not pointer.exists():
        initial = version(read(DEFAULTS / f'{name}.json'), '初始版本')
        save(root / f"{initial['version']}.json", initial, history=False)
        save(pointer, {'version': initial['version']}, history=False)
    return get(project, name, read(pointer)['version'])


def get(project, name, revision):
    if not re.fullmatch(r'[a-f0-9]{20}', revision):
        raise ValueError('Invalid prompt version')
    return read(folder(project, name) / f'{revision}.json')


def catalog(project):
    result = []
    for name in IDS:
        current = active(project, name)
        history = [read(p) for p in folder(project, name).glob('*.json') if p.name != 'active.json']
        result.append({'id': name, 'active': current, 'versions': sorted(history, key=lambda v:v['created_at'], reverse=True),
                       'allowed_parameters': sorted(PARAMETERS[name])})
    return result


def publish(project, data, expected):
    current = active(project, data['id'])
    if current['version'] != expected:
        raise ValueError('Prompt 已被修改，请重新载入后保存。')
    new = version(data, data.get('note', ''))
    destination = folder(project, data['id']) / f"{new['version']}.json"
    if not destination.exists():
        save(destination, new, history=False)
    save(destination.parent / 'active.json', {'version': new['version']})
    return catalog(project)


def activate(project, name, revision, expected):
    if active(project, name)['version'] != expected:
        raise ValueError('Prompt 已被修改，请重新载入。')
    get(project, name, revision)
    save(folder(project, name) / 'active.json', {'version': revision})
    return catalog(project)


def resolve(project, name, variables=None):
    current = active(project, name)
    variables = variables or {}
    missing = set(current['variables']) - variables.keys()
    if missing:
        raise ValueError(f'缺少模板变量：{sorted(missing)}')
    rendered = re.sub(r'\{\{\s*([A-Za-z_]\w*)\s*\}\}', lambda m: str(variables[m[1]]), current['body'])
    return rendered, {**current, 'resolved_variables': variables, 'rendered': rendered}
