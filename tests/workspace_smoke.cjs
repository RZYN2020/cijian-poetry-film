// Optional: NODE_PATH=/path/to/node_modules node tests/workspace_smoke.cjs
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const {spawn,execFileSync}=require('node:child_process');
const assert=require('node:assert/strict');
(async()=>{
  const repo=path.resolve(__dirname,'..'),temp=await fs.mkdtemp(path.join(os.tmpdir(),'cijian-workspace-'));
  let server,browser;
  try{
    const project=path.join(temp,'one');await fs.mkdir(project);
    const source=path.join(repo,'projects/huanxisha');
    const board=JSON.parse(await fs.readFile(path.join(source,'storyboard.json')));
    await fs.writeFile(path.join(project,'storyboard.json'),JSON.stringify(board));
    for(const f of new Set([...board.assets.map(a=>a.path),...board.scenes.map(s=>s.audio.path)])){
      await fs.mkdir(path.dirname(path.join(project,f)),{recursive:true});await fs.copyFile(path.join(source,f),path.join(project,f));
    }
    await fs.mkdir(path.join(temp,'two'));await fs.writeFile(path.join(temp,'two/storyboard.json'),JSON.stringify(board));
    execFileSync('uv',['run','ci-video','images',project,'--dry-run'],{cwd:repo});
    server=spawn('uv',['run','ci-video','edit',project,'--port','0'],{cwd:repo});
    const url=await new Promise((resolve,reject)=>{server.stdout.on('data',d=>{const m=d.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(m)resolve(m[0]);});server.on('error',reject);server.on('exit',c=>reject(new Error('Server exit '+c)));});
    browser=await chromium.launch({executablePath:path.join(repo,'node_modules/.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell')});
    const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));await page.goto(url);
    await page.locator('[data-pane=prompts]').click();await page.locator('#prompt-body').waitFor();
    const first=await page.locator('#prompt-version').inputValue();
    await page.locator('#prompt-body').fill('A quiet garden. {{visual_intent}}');
    await page.locator('#prompt-params').fill('{"quality":"low"}');
    await page.locator('#prompt-note').fill('Browser test version');
    await page.locator('#prompt-save').click();
    await page.waitForFunction(first=>document.querySelector('#prompt-version').value!==first,first);
    assert.equal(await page.locator('#prompt-version option').count(),2);
    await page.locator('#prompt-version').selectOption(first);await page.locator('#prompt-activate').click();
    await page.waitForFunction(first=>document.querySelector('#prompt-meta').textContent.includes(first.slice(0,8)),first);
    await page.locator('[data-pane=traces]').click();await page.locator('.trace-item').first().waitFor();
    await page.locator('#trace-status').selectOption('dry_run');
    await page.locator('.trace-item').first().click();await page.locator('.evaluation').waitFor();
    await page.getByLabel('评分',{exact:true}).selectOption('4');await page.getByLabel('评价标签',{exact:true}).fill('模板测试');await page.getByLabel('评价备注',{exact:true}).fill('需要减少描述');
    await page.locator('.evaluation button').click();await page.waitForFunction(()=>document.querySelector('#notice').textContent==='评价已保存');
    const data=await (await page.request.get(url+'/api/traces/export')).text();
    const rows=data.trim().split('\n').map(JSON.parse);assert.ok(rows.some(r=>r.evaluation?.score===4));
    assert.ok(rows.some(r=>r.status==='dry_run'&&r.request[0].prompt_snapshot.version===first));
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('#project-select').selectOption('two');await page.waitForFunction(()=>document.querySelector('#project-select').value==='two'&&document.querySelector('#save-state').textContent==='已保存到本机');
    const state=await (await page.request.get(url+'/api/state')).json();assert.equal(state.project_name,'two');
    assert.deepEqual(errors,[]);
    console.log('Workspace browser test passed: prompt versions/activation, dry-run trace, evaluation, JSONL, project switching, mobile.');
  }finally{if(browser)await browser.close();if(server){server.kill('SIGINT');await new Promise(r=>server.once('exit',r));}await fs.rm(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
