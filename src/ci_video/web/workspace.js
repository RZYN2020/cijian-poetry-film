let workspace, promptId='image', promptDirty=false, traceRows=[], traceSelected=null;
async function workspaceLoad() {
  workspace=await api('/api/workspace');
  $('project-select').replaceChildren(...workspace.projects.map(p=>option(p.id,p.id)));
  $('project-select').value=workspace.current;
  paintPrompts();
}
function currentPrompt(){return workspace.prompts.find(p=>p.id===promptId);}
function previewPrompt(){
  $('prompt-preview').textContent=$('prompt-body').value.replace(/\{\{\s*visual_intent\s*\}\}/g,()=>$('prompt-variable').value);
}
function paintPrompts(versionId){
  $('prompt-list').replaceChildren();
  for(const p of workspace.prompts){const b=document.createElement('button');b.className='prompt-item'+(p.id===promptId?' active':'');b.textContent=p.active.name+' · '+p.id;b.onclick=()=>{if(promptDirty&&!confirm('放弃尚未保存的 Prompt 修改？'))return;promptId=p.id;promptDirty=false;paintPrompts();};$('prompt-list').append(b);}
  const p=currentPrompt(),v=p.versions.find(v=>v.version===versionId)||p.active;
  $('prompt-version').replaceChildren(...p.versions.map(v=>option(v.version,`${v.version.slice(0,8)}${v.version===p.active.version?' · 当前':''} · ${v.note||v.created_at}`)));
  $('prompt-version').value=v.version;$('prompt-name').value=v.name;$('prompt-body').value=v.body;$('prompt-params').value=JSON.stringify(v.parameters,null,2);$('prompt-note').value='';
  $('prompt-meta').textContent=`当前版本 ${p.active.version.slice(0,8)} · ${p.versions.length} 个版本`;
  $('prompt-param-help').textContent=`可用参数：${p.allowed_parameters.join(', ')}。留空对象 {} 时使用服务默认配置。`;
  $('prompt-baseline').textContent=p.active.body+'\n\n'+JSON.stringify(p.active.parameters,null,2);
  $('prompt-variable-label').hidden=p.id!=='image';$('prompt-variable').value=state?.board.scenes[selected].visual_intent||'';previewPrompt();
  const help={image:'只生成分镜页面当前选中的镜头。调用已配置的生图 API，可能计费。',tts:'生成所有句子的朗诵，使用分镜页面选中的语音服务。Edge 只使用 edge_voice / edge_rate，不支持正文语气指令。',research:'重新整理研究包。不会自动修改分镜，生成结果需人工审核。',script:'生成 script.json，不自动重建 storyboard.json。'};
  $('prompt-run-help').textContent=help[p.id];
}
for(const id of ['prompt-name','prompt-body','prompt-params','prompt-note'])$(id).addEventListener('input',()=>{promptDirty=true;previewPrompt();});
$('prompt-variable').addEventListener('input',previewPrompt);
$('prompt-version').onchange=()=>{if(promptDirty&&!confirm('放弃尚未保存的 Prompt 修改？'))return;promptDirty=false;paintPrompts($('prompt-version').value);};
$('prompt-save').onclick=()=>execute(async()=>{
  const p=currentPrompt();workspace.prompts=await api('/api/prompt',{revision:state.revision,expected:p.active.version,prompt:{id:p.id,name:$('prompt-name').value,body:$('prompt-body').value,parameters:JSON.parse($('prompt-params').value),note:$('prompt-note').value}});
  promptDirty=false;paintPrompts();notice('版本已保存并启用');
});
$('prompt-activate').onclick=()=>execute(async()=>{
  const p=currentPrompt();workspace.prompts=await api('/api/prompt',{action:'activate',revision:state.revision,id:p.id,version:$('prompt-version').value,expected:p.active.version});promptDirty=false;paintPrompts();notice('历史版本已启用');
});
$('prompt-run').onclick=()=>execute(async()=>{
  if(promptDirty)throw new Error('请先保存或放弃 Prompt 修改。');
  const action={image:'images',tts:'tts',research:'research',script:'script'}[promptId];
  await job(action,{scene_id:state.board.scenes[selected].id,provider:$('provider').value});
});
$('project-select').onchange=()=>execute(async()=>{
  if((dirty||promptDirty)&&!confirm('切换项目将放弃尚未保存的修改，继续？')){$('project-select').value=workspace.current;return;}
  state=await api('/api/project',{revision:state.revision,project:$('project-select').value});dirty=false;promptDirty=false;selected=0;paint();await workspaceLoad();await loadTraces();
});
for(const b of document.querySelectorAll('[data-pane]'))b.onclick=async()=>{
  for(const item of document.querySelectorAll('[data-pane]'))item.classList.toggle('active',item===b);
  for(const id of ['edit','prompts','traces'])$(id+'-pane').hidden=id!==b.dataset.pane;
  try{if(b.dataset.pane==='prompts'&&!promptDirty)await workspaceLoad();if(b.dataset.pane==='traces')await loadTraces();}catch(e){notice(e.message);}
};
async function loadTraces(){const result=await api('/api/traces');traceRows=result.records;$('trace-count').textContent=`共 ${result.total} 条 · 显示最近 ${traceRows.length} 条` ;paintTraces();}
function paintTraces(){
  $('trace-list').replaceChildren();const query=$('trace-search').value.toLowerCase(),status=$('trace-status').value;
  for(const r of traceRows.filter(r=>(!status||r.status===status)&&JSON.stringify(r).toLowerCase().includes(query))){
    const b=document.createElement('button');b.className='trace-item'+(r.id===traceSelected?' active':'');
    const title=document.createElement('strong');title.textContent=`${r.stage} · ${r.status}`;
    const info=document.createElement('span');info.textContent=`${r.model||r.provider||r.kind} · ${r.duration_ms==null?'耗时未知':(r.duration_ms/1000).toFixed(2)+'s'}`;
    const extra=document.createElement('small');extra.textContent=`${r.started_at||'时间未记录'} · ${r.prompt_version?.slice(0,8)||'无版本'}${r.evaluation?.score?' · '+r.evaluation.score+'/5':''}`;
    b.append(title,info,extra);b.onclick=()=>showTrace(r.id).catch(e=>notice(e.message));$('trace-list').append(b);
  }
  if(!$('trace-list').children.length)$('trace-list').textContent='没有符合条件的运行记录。';
}
function block(label,value,parent){const details=document.createElement('details');details.open=true;const title=document.createElement('summary');title.textContent=label;const pre=document.createElement('pre');pre.textContent=typeof value==='string'?value:JSON.stringify(value??null,null,2);details.append(title,pre);parent.append(details);}
async function showTrace(id){
  const t=await api('/api/trace/'+id);traceSelected=id;paintTraces();const root=$('trace-detail');root.replaceChildren();
  const heading=document.createElement('h2');heading.textContent=`${t.stage} / ${t.status}`;root.append(heading);
  block('调用信息',{id:t.id,run_id:t.run_id,parent_id:t.parent_id,kind:t.kind,provider:t.provider,model:t.model,started_at:t.started_at,duration_ms:t.duration_ms,usage:t.usage,cost:t.cost,note:t.note,error:t.error},root);
  const form=document.createElement('form');form.className='evaluation';
  const score=document.createElement('select');score.setAttribute('aria-label','评分');score.append(option('','未评分'),...[1,2,3,4,5].map(n=>option(String(n),n+' / 5')));score.value=t.evaluation?.score||'';
  const tags=document.createElement('input');tags.placeholder='标签，逗号分隔，例如：停顿不足, 构图杂乱';tags.setAttribute('aria-label','评价标签');tags.value=(t.evaluation?.tags||[]).join(', ');
  const note=document.createElement('textarea');note.placeholder='问题和下一次要调整的内容';note.setAttribute('aria-label','评价备注');note.value=t.evaluation?.note||'';
  const submit=document.createElement('button');submit.textContent='保存评价';form.append(score,tags,note,submit);
  form.onsubmit=e=>{e.preventDefault();execute(async()=>{await api('/api/evaluation',{revision:state.revision,id,score:score.value?Number(score.value):null,tags:tags.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean),note:note.value});notice('评价已保存');await loadTraces();});};root.append(form);
  const compare=document.createElement('select');compare.setAttribute('aria-label','选择对照运行');compare.append(option('','选择另一条记录对照'),...traceRows.filter(r=>r.id!==id).map(r=>option(r.id,`${r.stage} · ${r.status} · ${r.model||''} · ${r.id.slice(0,8)}`)));root.append(compare);
  const comparison=document.createElement('div');root.append(comparison);compare.onchange=async()=>{comparison.replaceChildren();if(compare.value){const other=await api('/api/trace/'+compare.value);block('对照运行：Prompt / 请求 / 输出',{prompt:other.prompt,request:other.request,response:other.response,artifacts:other.artifacts,evaluation:other.evaluation},comparison);}};
  block('Prompt 快照',t.prompt,root);block('实际请求',t.request??t.inputs,root);block('响应 / 结果',t.response??t.result,root);block('输出文件',t.artifacts,root);
  for(const a of t.artifacts||[]){if(!a.path)continue;let el;if(/\.(png|jpe?g|webp)$/i.test(a.path)){el=document.createElement('img');el.alt='本次运行生成的图片';el.style.maxWidth='260px';}else if(/\.(mp3|wav|m4a)$/i.test(a.path)){el=document.createElement('audio');el.controls=true;}else continue;el.src=media(a.path);root.append(el);}
}
$('trace-refresh').onclick=()=>loadTraces().catch(e=>notice(e.message));$('trace-search').oninput=paintTraces;$('trace-status').onchange=paintTraces;
window.addEventListener('beforeunload',event=>{if(promptDirty){event.preventDefault();event.returnValue='';}});
workspaceLoad().catch(e=>notice(e.message));
