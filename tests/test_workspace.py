import asyncio
import base64
import io
import json

import httpx
from PIL import Image
import pytest

from ci_video import prompts, traces, media_api
from ci_video.speech import obtain_audio
from ci_video.storage import digest, read, save


def test_prompt_versions_are_immutable_and_can_be_activated(tmp_path):
    first = prompts.active(tmp_path,'image')
    text, snapshot = prompts.resolve(tmp_path,'image',{'visual_intent':'月下空园'})
    assert text.endswith('月下空园')
    changed = {**first,'body':'A garden. {{visual_intent}}','parameters':{'quality':'low'}}
    prompts.publish(tmp_path,changed,first['version'])
    second = prompts.active(tmp_path,'image')
    assert second['version'] != first['version']
    assert prompts.get(tmp_path,'image',first['version']) == first
    assert snapshot['rendered'] == text
    with pytest.raises(ValueError,match='已被修改'):
        prompts.publish(tmp_path,changed,first['version'])
    prompts.activate(tmp_path,'image',first['version'],second['version'])
    assert prompts.active(tmp_path,'image') == first


def test_prompt_validation(tmp_path):
    p = prompts.active(tmp_path,'image')
    with pytest.raises(ValueError,match='缺少模板变量'):
        prompts.resolve(tmp_path,'image')
    with pytest.raises(ValueError):
        prompts.publish(tmp_path,{**p,'body':'{{unknown}}'},p['version'])
    with pytest.raises(ValueError):
        prompts.publish(tmp_path,{**p,'parameters':{'api_key':'secret'}},p['version'])


def test_nested_traces_failures_feedback_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv('TEST_API_KEY','known-secret-value')
    with traces.Trace(tmp_path,'pipeline','stage') as root:
        with pytest.raises(ValueError):
            with traces.Trace(tmp_path,'image') as child:
                child.update(request={'api_key':'anything','prompt':'known-secret-value'})
                raise ValueError('known-secret-value failed')
    records = traces.records(tmp_path)
    result = next(r for r in records if r['id']==child.data['id'])
    assert result['status']=='failed'
    assert result['parent_id']==root.data['id'] and result['run_id']==root.data['run_id']
    assert result['duration_ms']>=0 and result['finished_at']
    original = child.path.read_bytes()
    traces.annotate(tmp_path,result['id'],2,'图像过亮',['画面'])
    assert child.path.read_bytes()==original
    exported = traces.export(tmp_path)
    assert 'known-secret-value' not in exported and 'anything' not in exported
    assert any(r['evaluation'] and r['evaluation']['score']==2 for r in map(json.loads,exported.splitlines()))


def test_image_trace_links_actual_request_response_usage_and_asset(tmp_path, monkeypatch):
    p=prompts.active(tmp_path,'image')
    prompts.publish(tmp_path,{**p,'parameters':{'model':'test-image','quality':'low'}},p['version'])
    text,snapshot=prompts.resolve(tmp_path,'image',{'visual_intent':'test garden'})
    buf=io.BytesIO();Image.new('RGB',(8,8)).save(buf,format='PNG')
    monkeypatch.setattr(media_api,'settings',lambda _:('https://example.org/v1','test-key','default-model'))
    requests=[]
    def post(*args,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(buf.getvalue()).decode()}],'usage':{'total_tokens':12}})
    monkeypatch.setattr(httpx,'post',post)
    media_api.image_request(tmp_path,text,tmp_path/'assets/test.png',snapshot)
    t=traces.records(tmp_path)[0]
    assert t['status']=='complete' and t['model']=='test-image'
    assert t['request']==requests[0] and t['prompt']['version']==snapshot['version']
    assert t['usage']['total_tokens']==12 and t['cost'] is None
    assert t['artifacts'][0]['sha256']==digest(buf.getvalue())


def test_cached_speech_is_recorded_without_network(tmp_path):
    path=tmp_path/'audio/test.mp3';path.parent.mkdir();path.write_bytes(b'cached media fixture')
    save(path.with_suffix('.json'),{'sha256':digest(path.read_bytes()),'duration':3,'events':[]},history=False)
    _,p=prompts.resolve(tmp_path,'tts')
    result=asyncio.run(obtain_audio(tmp_path,'s01','一曲新词酒一杯','edge','edge','voice','-35%','',path,p))
    t=traces.records(tmp_path)[0]
    assert t['status']=='cached' and t['scene_id']=='s01'
    assert result['duration']==3 and t['artifacts'][0]['path']=='audio/test.mp3'


def test_legacy_import_is_idempotent_and_does_not_invent_usage(tmp_path):
    save(tmp_path/'runs/tts-old.json',{'provider':'old','request':{'input':'poem'},'status':'complete'},history=False)
    assert traces.import_legacy(tmp_path)==1
    assert traces.import_legacy(tmp_path)==0
    t=traces.records(tmp_path)[0]
    assert t['kind']=='legacy' and t['duration_ms'] is None and t['usage'] is None and t['prompt'] is None


def test_llm_uses_versioned_prompt_and_records_invalid_output(tmp_path, monkeypatch):
    from pydantic import BaseModel
    from ci_video.llm import generate
    class Output(BaseModel):
        value: str
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-private-secret')
    monkeypatch.setenv('LLM_PROVIDER','deepseek')
    p=prompts.active(tmp_path,'research')
    prompts.publish(tmp_path,{**p,'body':'只整理来源，输出 JSON。','parameters':{'temperature':.2}},p['version'])
    requests=[]
    def post(*args,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"value":"ok"}'}}],'usage':{'total_tokens':20}})
    monkeypatch.setattr(httpx,'post',post)
    parsed,run=generate(tmp_path,'research',Output,{'source':'test'})
    assert parsed.value=='ok' and requests[0]['temperature']==.2
    assert requests[0]['messages'][0]['content'].startswith('只整理来源')
    t=traces.records(tmp_path)[0]
    assert t['stage']=='research' and t['usage']['total_tokens']==20
    assert read(run)['trace_id']==t['id']
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'invalid JSON'}}]}))
    with pytest.raises(ValueError):
        generate(tmp_path,'research',Output,{'source':'test'})
    t=traces.records(tmp_path)[0]
    assert t['status']=='failed' and t['response']['choices'][0]['message']['content']=='invalid JSON'
