import base64
import io
import json
from pathlib import Path
import threading

import httpx
from PIL import Image
import pytest

from ci_video.editor import Conflict, Editor, make_server
from ci_video.storage import read, save


@pytest.fixture
def project(tmp_path):
    data = read(Path(__file__).parents[1] / 'projects/huanxisha/storyboard.json')
    save(tmp_path / 'storyboard.json', data, history=False)
    return tmp_path


def edits(state):
    b = state['board']
    return {'revision': state['revision'], 'scenes': [dict(id=s['id'], duration=s['duration'],
        offset=s['audio']['offset'], asset_id=s['asset_refs'][0], visual_intent=s['visual_intent']) for s in b['scenes']],
        'music': {k: b[k] for k in ['bgm_path', 'bgm_start', 'bgm_volume', 'bgm_fade', 'bgm_duck']}}


def test_edit_moves_audio_and_subtitle_preserves_poem(project):
    editor = Editor(project)
    before = editor.snapshot()
    payload = edits(before)
    payload['scenes'][0]['offset'] += .5
    after = editor.update(payload)['board']
    first = before['board']['scenes'][0]
    assert after['scenes'][0]['audio']['offset'] == first['audio']['offset'] + .5
    assert after['scenes'][0]['subtitle'][0]['start'] == first['subtitle'][0]['start'] + .5
    assert after['scenes'][0]['narration'] == first['narration']
    assert list((project / 'history').glob('*.json'))
    # A stale browser must not overwrite the change.
    with pytest.raises(Conflict):
        editor.update(payload)


def test_invalid_timing_is_not_saved(project):
    editor = Editor(project)
    before = (project / 'storyboard.json').read_bytes()
    payload = edits(editor.snapshot())
    payload['scenes'][0]['duration'] = 1
    with pytest.raises(ValueError):
        editor.update(payload)
    assert (project / 'storyboard.json').read_bytes() == before


def test_background_job_blocks_edits(project):
    editor = Editor(project)
    payload = edits(editor.snapshot())
    editor.job['status'] = 'running'
    with pytest.raises(Conflict):
        editor.update(payload)


def test_import_image_preserves_attribution_and_replaces_only_selected(project):
    editor = Editor(project)
    before = editor.snapshot()
    buf = io.BytesIO()
    Image.new('RGB', (8, 8)).save(buf, format='PNG')
    result = editor.upload(dict(revision=before['revision'], kind='image', scene_id='s02',
        name='garden.png', data=base64.b64encode(buf.getvalue()).decode(), source='Own artwork',
        creator='Test artist', license='Own work'))
    assert result['board']['scenes'][0] == before['board']['scenes'][0]
    aid = result['board']['scenes'][1]['asset_refs'][0]
    asset = next(a for a in result['board']['assets'] if a['id'] == aid)
    assert asset['creator'] == 'Test artist'
    assert (project / asset['path']).read_bytes() == buf.getvalue()
    assert read(project / 'assets/manifest.json') == result['board']['assets']


@pytest.fixture
def server(project):
    server = make_server(project, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def test_local_session_and_media_ranges(server, project):
    (project / 'output.mp4').write_bytes(b'0123456789')
    url = f'http://127.0.0.1:{server.server_port}'
    with httpx.Client(base_url=url, trust_env=False) as client:
        assert client.get('/').status_code == 200
        state = client.get('/api/state').json()
        assert client.post('/api/save', json=edits(state)).status_code == 403
        headers = {'X-Editor-Token': server.editor.token, 'Origin': 'https://untrusted.example'}
        assert client.post('/api/save', headers=headers, json=edits(state)).status_code == 403
        assert client.get('/api/state', headers={'Host': 'untrusted.example'}).status_code == 403
        response = client.get('/media/output.mp4', headers={'Range': 'bytes=2-5'})
        assert response.status_code == 206 and response.content == b'2345'
        assert response.headers['Content-Range'] == 'bytes 2-5/10'
        assert client.get('/media/.env.local').status_code == 404
        assert client.get('/media/output.mp4', headers={'Range': 'bytes=500-'}).status_code == 416
        assert client.get('/media/output.mp4', headers={'Range': 'bytes=-3'}).content == b'789'
