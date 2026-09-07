const $ = (id) => document.getElementById(id);
let state, selected = 0, dirty = false, busy = false, uploadKind = 'image', pollTimer;
const token = document.querySelector('meta[name="editor-token"]').content;
const media = (path) => '/media/' + path.split('/').map(encodeURIComponent).join('/');
const assetById = (id) => state.board.assets.find(a => a.id === id);
function notice(text) { $('notice').textContent = text; $('notice').style.display = 'block'; clearTimeout(notice.timer); notice.timer = setTimeout(() => $('notice').style.display = 'none', 7000); }
async function api(path, data) {
  const response = await fetch(path, data ? {method:'POST', headers:{'Content-Type':'application/json','X-Editor-Token':token}, body:JSON.stringify(data)} : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function option(value, text) { const node = document.createElement('option'); node.value=value; node.textContent=text; return node; }
function markDirty() { dirty=true; $('save-state').textContent='有未保存修改'; $('output-state').textContent='当前修改尚未导出。下方为上次成片。'; }
function controls() {
  const running = busy || state?.job.status === 'running';
  document.querySelectorAll('.inspector input,.inspector textarea,.inspector select,.inspector button,#save,#render,#reload').forEach(el=>el.disabled=running);
  $('save-state').textContent = running ? '任务进行中…' : dirty ? '有未保存修改' : '已保存到本机';
}
function paintList() {
  $('scene-list').replaceChildren(); $('timeline').replaceChildren();
  state.board.scenes.forEach((scene, index)=>{
    const a=assetById(scene.asset_refs[0]);
    const button=document.createElement('button'); button.className='scene-card'+(index===selected?' active':'');
    const img=document.createElement('img'); img.src=a.kind==='image'?media(a.path):''; img.alt='';
    const info=document.createElement('div');
    for (const [cls,text] of [['num',String(index+1).padStart(2,'0')],['line',scene.narration],['seconds',`${scene.duration.toFixed(2)} 秒`]]) {
      const item=document.createElement('div');item.className=cls;item.textContent=text;info.append(item);
    }
    button.append(img,info);button.onclick=()=>{selected=index;paintScene();paintList();}; $('scene-list').append(button);
    const mini=document.createElement('button'); mini.className=index===selected?'active':'';mini.style.flex=scene.duration;
    if(a.kind==='image') mini.style.backgroundImage=`url("${media(a.path)}")`;
    const label=document.createElement('span');label.textContent=String(index+1).padStart(2,'0');mini.append(label);mini.setAttribute('aria-label',scene.narration);mini.onclick=button.onclick;$('timeline').append(mini);
  });
}
function paintScene() {
  const scene=state.board.scenes[selected], a=assetById(scene.asset_refs[0]);
  $('shot-label').textContent=`镜头 ${String(selected+1).padStart(2,'0')} / ${state.board.scenes.length}`;
  $('scene-title').textContent=scene.narration; $('poem-line').textContent=scene.narration;
  $('picture').hidden=a.kind!=='image'; $('picture-video').hidden=a.kind!=='video';
  const visual=$(a.kind==='video'?'picture-video':'picture');visual.src=media(a.path);visual.style.objectPosition=a.object_position;
  $('picture-video').pause();
  $('duration').value=scene.duration; $('offset').value=scene.audio?.offset??scene.voice_offset;
  $('visual').value=scene.visual_intent;
  $('asset').replaceChildren(...state.board.assets.filter(a=>['image','video'].includes(a.kind)).map(a=>option(a.id,a.id)));
  $('asset').value=a.id;
  $('voice').pause(); $('voice').hidden=!scene.audio;
  if(scene.audio) $('voice').src=media(scene.audio.path);
  $('voice-details').textContent=scene.audio?`${scene.audio.voice} · ${scene.audio.duration.toFixed(2)} 秒 · ${scene.audio.provider}`:'尚未生成朗诵';
  $('scene-summary').textContent=`${scene.duration.toFixed(2)} 秒画面 · ${Number($('offset').value).toFixed(1)} 秒后开始朗诵`;
}
function paintMusic() {
  const b=state.board;
  $('music').replaceChildren(option('','不使用音乐'),...b.assets.filter(a=>a.kind==='audio').map(a=>option(a.path,a.description||a.id)));
  $('music').value=b.bgm_path||''; $('music-start').value=b.bgm_start; $('fade').value=b.bgm_fade;
  $('volume').value=b.bgm_volume; $('duck').value=b.bgm_duck; musicDetails();
  $('catalog').replaceChildren(...state.catalog.map(a=>option(a.id,a.description||a.id)));
}
function musicDetails() {
  const b=state.board, a=b.assets.find(a=>a.path===b.bgm_path);
  $('volume-value').value=`${Math.round(b.bgm_volume*100)}%`; $('duck-value').value=`${Math.round(b.bgm_duck*100)}%`;
  const player=$('music-audio');player.volume=b.bgm_volume;player.hidden=!a;
  if(a && player.getAttribute('src')!==media(a.path)) player.src=media(a.path);
  if(!a) player.pause();
  $('music-credit').textContent=a?`${a.creator} · ${a.license}`:'';
}
function paintOutput() {
  $('output').hidden=!state.output_exists; $('download').hidden=!state.output_exists;
  const url=media('output.mp4')+'?v='+state.output_version;
  if(state.output_exists && $('output').getAttribute('src')!==url) { $('output').src=url; $('download').href=url; }
  $('output-state').textContent=!state.output_exists?'还没有成片。保存后点击「导出视频」。':state.output_current&&!dirty?'成片与当前保存的分镜一致。':'分镜已有变化，下方为上次成片。导出后更新。';
}
function paintJob() {
  const job=state.job;$('job-panel').hidden=job.status==='idle';
  $('job-title').textContent=job.status==='running'?'正在处理，请稍候':job.status==='complete'?'任务完成':'任务未完成';
  $('job-log').textContent=job.log;
}
function paint() {
  $('title').textContent=state.board.poem_title; $('author').textContent=`${state.board.author} · 纯词朗诵`;
  $('scene-count').textContent=`${state.board.scenes.length} 个镜头`;
  paintList();paintScene();paintMusic();paintOutput();paintJob();controls();
}
async function load() {state=await api('/api/state');dirty=false;paint();if(state.job.status==='running') schedulePoll();}
function payload() {
  const b=state.board;
  return {revision:state.revision,scenes:b.scenes.map(s=>({id:s.id,duration:s.duration,offset:s.audio?.offset??s.voice_offset,asset_id:s.asset_refs[0],visual_intent:s.visual_intent})),
    music:Object.fromEntries(['bgm_path','bgm_start','bgm_volume','bgm_fade','bgm_duck'].map(k=>[k,b[k]]))};
}
async function save() { state=await api('/api/save',payload());dirty=false;paint(); }
async function execute(fn) { if(busy)return;busy=true;controls();try{await fn();}catch(e){notice(e.message);}finally{busy=false;controls();} }
async function job(action, extra={}) { await save();state=await api('/api/job',{revision:state.revision,action,...extra});paintJob();schedulePoll(); }
function schedulePoll() {clearTimeout(pollTimer);pollTimer=setTimeout(async()=>{try{const latest=await api('/api/state');state.job=latest.job;paintJob();controls();if(latest.job.status==='running')schedulePoll();else{state=latest;dirty=false;paint();notice(latest.job.status==='complete'?'已完成':'任务失败，详情见页面底部');}}catch(e){notice(e.message);schedulePoll();}},1500);}
for(const id of ['duration','offset','visual','asset']) $(id).addEventListener('input',()=>{
  const s=state.board.scenes[selected];
  if(id==='duration')s.duration=Number($(id).value);
  if(id==='offset'){s.voice_offset=Number($(id).value);if(s.audio)s.audio.offset=s.voice_offset;}
  if(id==='visual')s.visual_intent=$(id).value;
  if(id==='asset'){s.asset_refs=[$(id).value];paintScene();}
  markDirty(); if(id!=='visual')paintList();
});
for(const [id,key] of [['music','bgm_path'],['volume','bgm_volume'],['music-start','bgm_start'],['fade','bgm_fade'],['duck','bgm_duck']]) $(id).addEventListener('input',()=>{
  state.board[key]=id==='music'?$(id).value||null:Number($(id).value);markDirty();musicDetails();
  if(id==='music-start' && Number.isFinite($('music-audio').duration)) $('music-audio').currentTime=Math.min(state.board.bgm_start,$('music-audio').duration);
});
$('music-audio').addEventListener('loadedmetadata',()=>{if(state)$('music-audio').currentTime=Math.min(state.board.bgm_start,$('music-audio').duration||0);});
document.addEventListener('play',e=>{document.querySelectorAll('audio,video').forEach(el=>{if(el!==e.target)el.pause();});},true);
$('save').onclick=()=>execute(async()=>{await save();notice('已保存');});
$('reload').onclick=()=>{if(!dirty||confirm('放弃尚未保存的修改并重新载入？'))execute(load);};
$('render').onclick=()=>execute(()=>job('render'));
$('tts').onclick=()=>execute(()=>job('tts',{provider:$('provider').value}));
$('download-music').onclick=()=>execute(()=>job('bgm',{track:$('catalog').value}));
function uploadDialog(kind){uploadKind=kind;$('upload-form').reset();$('upload-title').textContent=kind==='image'?'替换当前镜头图片':'导入背景音乐';$('upload-file').accept=kind==='image'?'.png,.jpg,.jpeg,.webp':'.mp3,.wav,.m4a';$('upload-dialog').showModal();}
$('import-image').onclick=()=>uploadDialog('image');$('import-music').onclick=()=>uploadDialog('audio');$('cancel-upload').onclick=()=>$('upload-dialog').close();
$('upload-form').onsubmit=e=>{e.preventDefault();const file=$('upload-file').files[0];if(!file)return;if(file.size>30*1024*1024)return notice('文件超过 30 MB');execute(async()=>{
  await save();
  const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});
  state=await api('/api/upload',{revision:state.revision,kind:uploadKind,scene_id:uploadKind==='image'?state.board.scenes[selected].id:null,name:file.name,data,source:$('upload-source').value,creator:$('upload-creator').value,license:$('upload-license').value,attribution:$('upload-credit').value});
  $('upload-dialog').close();dirty=false;paint();notice('素材已导入并保存');
});};
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
load().catch(e=>notice(e.message));
