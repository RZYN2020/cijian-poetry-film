import copy
import json
from pathlib import Path

import httpx
import pytest

from ci_video.models import Storyboard
from ci_video.pipeline import validate_recital
from ci_video import media_api


@pytest.fixture
def board():
    return json.loads((Path(__file__).parents[1] / 'projects/huanxisha/storyboard.json').read_text())


def test_recital_rejects_extra_explanation(board):
    validate_recital(Storyboard.model_validate(board))
    board['scenes'][0]['narration'] += '这表达了怀旧。'
    with pytest.raises(ValueError):
        validate_recital(Storyboard.model_validate(board))


def test_bgm_cannot_escape_project(board):
    board['bgm_path'] = '../private.mp3'
    with pytest.raises(ValueError):
        Storyboard.model_validate(board)


def test_quota_failure_no_retry_or_secret_log(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(media_api, 'settings', lambda _: ('https://example.org/v1', 'secret-test', 'model'))
    def post(*args, **kwargs):
        calls.append(args)
        return httpx.Response(429, json={'error': {'code': 'credit_balance_exhausted', 'message': 'secret-test'}})
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(media_api.MediaError, match='credit_balance_exhausted'):
        media_api.post(tmp_path, 'TTS', '/audio/speech', {'input': '一曲新词酒一杯'})
    assert len(calls) == 1
    logs = list((tmp_path / 'runs').glob('*.json'))
    assert len(logs) == 1
    assert 'secret-test' not in logs[0].read_text()
    assert json.loads(logs[0].read_text())['status'] == 'failed'


def test_custom_provider_does_not_receive_openai_key(monkeypatch):
    monkeypatch.setattr(media_api, 'load_dotenv', lambda *a: None)
    monkeypatch.setenv('IMAGE_BASE_URL', 'https://example.org/v1')
    monkeypatch.delenv('IMAGE_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'secret-test')
    assert media_api.settings('IMAGE')[1] is None


def test_image_base64_response(tmp_path, monkeypatch):
    import base64
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (16, 16)).save(buf, format='PNG')
    monkeypatch.setattr(media_api, 'settings', lambda _: ('https://example.org/v1', 'test', 'image-model'))
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(buf.getvalue()).decode()}]}))
    dest = tmp_path / 'assets/image.png'
    result = media_api.image_request(tmp_path, 'garden', dest)
    assert result['status'] == 'complete'
    assert dest.read_bytes() == buf.getvalue()
