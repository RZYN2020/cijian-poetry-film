"""Local invocation records. Binary results remain files; feedback is separate."""
from contextvars import ContextVar
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from .storage import digest, now, read, save

CURRENT = ContextVar('ci_trace', default=None)


def clean(value):
    if isinstance(value, type):
        return value.__name__
    if hasattr(value, 'model_dump'):
        return clean(value.model_dump())
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if any(s in str(k).lower() for s in ['api_key', 'authorization', 'password', 'secret']) else clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, bytes):
        return {'bytes': len(value), 'sha256': digest(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if (key.endswith('_API_KEY') or key.endswith('_TOKEN')) and len(secret) >= 8:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'sk-(?:proj-)?[A-Za-z0-9_-]{16,}', '[REDACTED]', value)
        return re.sub(r'(https?://[^\s?]+)\?[^\s"<>]+', r'\1?[REDACTED_QUERY]', value)
    return value


class Trace:
    def __init__(self, project, stage, kind='model', **fields):
        self.project = Path(project)
        self.start = time.perf_counter()
        parent = CURRENT.get()
        identifier = uuid4().hex
        self.data = {'schema_version': '1.0', 'id': identifier,
            'run_id': parent.data['run_id'] if parent else os.getenv('CI_RUN_ID', identifier),
            'parent_id': parent.data['id'] if parent else os.getenv('CI_PARENT_TRACE_ID'),
            'project_id': self.project.name, 'stage': stage, 'kind': kind, 'status': 'running',
            'started_at': now(), 'finished_at': None, 'duration_ms': None, 'provider': None,
            'model': None, 'prompt': parent.data.get('prompt') if parent else None, 'request': None, 'response': None, 'usage': None,
            'cost': None, 'artifacts': [], 'error': None, **fields}
        self.path = self.project / 'traces' / f'{identifier}.json'
        self.flush()

    def flush(self):
        save(self.path, clean(self.data), history=False)

    def update(self, **fields):
        self.data.update(fields)
        self.flush()

    def __enter__(self):
        self.token = CURRENT.set(self)
        return self

    def __exit__(self, typ, exc, tb):
        failed = exc is not None and not (isinstance(exc, SystemExit) and exc.code in (0, None))
        self.data.update(status='failed' if failed else self.data.get('result_status', 'complete'),
                         finished_at=now(), duration_ms=round((time.perf_counter()-self.start)*1000, 2))
        if failed and not self.data.get('error'):
            self.data['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
        self.flush()
        CURRENT.reset(self.token)


def update(**fields):
    trace = CURRENT.get()
    if trace:
        trace.update(**fields)


def traced(stage, kind='model'):
    def decorate(fn):
        def setup(args, kwargs):
            bound = inspect.signature(fn).bind(*args, **kwargs)
            values = dict(bound.arguments)
            project = values.pop('project')
            return Trace(project, stage, kind, inputs=values)
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def wrapped(*args, **kwargs):
                with setup(args, kwargs) as trace:
                    result = await fn(*args, **kwargs)
                    trace.update(result=result)
                    return result
        else:
            @wraps(fn)
            def wrapped(*args, **kwargs):
                with setup(args, kwargs) as trace:
                    result = fn(*args, **kwargs)
                    trace.update(result=result)
                    return result
        return wrapped
    return decorate


def records(project):
    entries = []
    for path in (Path(project) / 'traces').glob('*.json'):
        try:
            item = clean(read(path))
            feedback = Path(project) / 'evaluations' / f"{item['id']}.json"
            item['evaluation'] = read(feedback) if feedback.exists() else None
            entries.append(item)
        except (ValueError, OSError, KeyError):
            continue
    return sorted(entries, key=lambda e:e.get('started_at') or '', reverse=True)


def annotate(project, identifier, score, note, tags):
    if not re.fullmatch(r'[a-f0-9]{32}', identifier) or not (Path(project) / 'traces' / f'{identifier}.json').is_file():
        raise ValueError('Unknown trace')
    if score is not None and (type(score) is not int or not 1 <= score <= 5):
        raise ValueError('评分范围为 1–5')
    if not isinstance(note, str) or not isinstance(tags, list) or any(not isinstance(t,str) for t in tags):
        raise ValueError('Invalid feedback')
    evaluation = clean({'trace_id': identifier, 'score': score, 'note': note[:10000], 'tags': tags, 'updated_at': now()})
    save(Path(project) / 'evaluations' / f'{identifier}.json', evaluation)
    return evaluation


def export(project):
    return '\n'.join(json.dumps(item, ensure_ascii=False) for item in records(project)) + '\n'


def import_legacy(project):
    """Idempotent import, explicitly preserve unknowns instead of inventing them."""
    project = Path(project)
    count = 0
    for path in (project / 'runs').glob('*.json'):
        try:
            old = read(path)
        except (ValueError, OSError):
            continue
        identifier = digest(str(path.name))[:32]
        dest = project / 'traces' / f'{identifier}.json'
        if dest.exists():
            continue
        # New invocations already have a trace and retain legacy logs for replay compatibility.
        if old.get('trace_id'):
            continue
        stage = old.get('stage', path.name.split('-')[0])
        save(dest, clean({'schema_version': '1.0', 'id': identifier, 'run_id': identifier, 'parent_id': None,
            'project_id': project.name, 'stage': stage, 'kind': 'legacy', 'status': 'legacy',
            'started_at': old.get('created_at'), 'finished_at': None, 'duration_ms': None,
            'provider': old.get('provider'), 'model': old.get('model', old.get('request',{}).get('model')),
            'prompt': None, 'request': old.get('request'), 'response': old.get('response'),
            'usage': old.get('usage') or (old.get('response') or {}).get('usage'), 'cost': None,
            'artifacts': [], 'error': old.get('error'), 'legacy_file': str(path.relative_to(project)),
            'legacy_record': old, 'note': '旧日志导入；未记录的时间、Prompt 版本、用量保持空值。'}), history=False)
        count += 1
    board_path = project / 'storyboard.json'
    if board_path.exists():
        board = read(board_path)
        for asset in board.get('assets', []):
            generation = asset.get('generation')
            if not generation or generation.get('trace_id'):
                continue
            identifier = digest('imported-asset-' + asset.get('sha256',asset['id']))[:32]
            dest = project / 'traces' / f'{identifier}.json'
            if dest.exists():
                continue
            save(dest, clean({'schema_version':'1.0','id':identifier,'run_id':identifier,'parent_id':None,
                'project_id':project.name,'stage':'image','kind':'imported_artifact','status':'imported',
                'started_at':generation.get('created_at'),'finished_at':None,'duration_ms':None,
                'provider':generation.get('provider'),'model':generation.get('model'),
                'prompt':{'rendered':generation.get('prompt'),'version':None},'request':None,'response':None,
                'usage':None,'cost':None,'error':None,'artifacts':[{'path':asset['path'],'sha256':asset.get('sha256')}],
                'note':'既有素材元数据，未观测原始 API 调用；不是完整调用 Trace。'}), history=False)
            count += 1
        known_audio = {a.get('sha256') for t in records(project) for a in t.get('artifacts',[])}
        for scene in board.get('scenes',[]):
            audio = scene.get('audio')
            if not audio or audio.get('file_sha256') in known_audio:
                continue
            identifier = digest('imported-audio-' + audio['file_sha256'])[:32]
            save(project/'traces'/f'{identifier}.json', clean({'schema_version':'1.0','id':identifier,'run_id':identifier,'parent_id':None,
                'project_id':project.name,'stage':'speech','scene_id':scene['id'],'kind':'imported_artifact','status':'imported',
                'started_at':None,'finished_at':None,'duration_ms':None,'provider':audio['provider'],'model':audio.get('model'),
                'prompt':None,'request':None,'inputs':{'text':scene['narration'],'voice':audio['voice'],'rate':audio['rate']},
                'response':None,'usage':None,'cost':None,'error':None,
                'artifacts':[{'path':audio['path'],'sha256':audio['file_sha256']}],
                'note':'既有音频元数据，原始调用时间与请求未记录。'}),history=False)
            count += 1
    return count
