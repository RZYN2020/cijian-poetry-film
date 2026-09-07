// Optional browser integration test. Requires Playwright and Remotion's downloaded Chromium.
// NODE_PATH=/path/to/node_modules node tests/editor_smoke.cjs
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {spawn, execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');

(async () => {
  const repo = path.resolve(__dirname, '..');
  const source = path.join(repo, 'projects/huanxisha');
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'cijian-editor-'));
  let server, browser;
  try {
    const board = JSON.parse(await fs.readFile(path.join(source, 'storyboard.json')));
    board.width = 360; board.height = 640;
    // Deliberately omit research.json/project.json/script.json: export must be independent.
    await fs.writeFile(path.join(temp, 'storyboard.json'), JSON.stringify(board));
    for (const file of new Set([...board.assets.map(a=>a.path), ...board.scenes.map(s=>s.audio.path)])) {
      await fs.mkdir(path.dirname(path.join(temp,file)),{recursive:true});
      await fs.copyFile(path.join(source,file),path.join(temp,file));
    }
    server = spawn('uv',['run','ci-video','edit',temp,'--port','0'],{cwd:repo});
    const url = await new Promise((resolve,reject)=>{
      server.stdout.on('data',chunk=>{const m=chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(m)resolve(m[0]);});
      server.on('error',reject);server.on('exit',code=>reject(new Error('Server exited '+code)));
    });
    browser = await chromium.launch({executablePath:path.join(repo,'node_modules/.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell')});
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    await page.locator('.scene-card').last().waitFor();
    assert.equal(await page.locator('.scene-card').count(),6);
    await page.locator('#offset').fill('1.7');
    await page.locator('#save').click();
    await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='已保存到本机');
    const saved=JSON.parse(await fs.readFile(path.join(temp,'storyboard.json')));
    assert.equal(saved.scenes[0].audio.offset,1.7);
    assert.ok(Math.abs(saved.scenes[0].subtitle[0].start-board.scenes[0].subtitle[0].start-.5)<1e-6);
    await page.locator('.scene-card').nth(4).click();
    assert.equal(await page.locator('#scene-title').textContent(),board.scenes[4].narration);
    await page.locator('#import-image').click();
    const image=board.assets.find(a=>a.id===board.scenes[0].asset_refs[0]);
    await page.locator('#upload-file').setInputFiles(path.join(source,image.path));
    await page.locator('#upload-source').fill('Browser test fixture');
    await page.locator('#upload-creator').fill('Test');
    await page.locator('#upload-license').fill('Test fixture only');
    await page.locator('#upload-form button[type=submit]').click();
    await page.locator('#upload-dialog').waitFor({state:'hidden'});
    assert.match(JSON.parse(await fs.readFile(path.join(temp,'storyboard.json'))).scenes[4].asset_refs[0],/^local-/);
    await page.locator('#render').click();
    await page.waitForFunction(()=>document.querySelector('#job-title').textContent==='任务完成',{},{timeout:240000});
    const report=JSON.parse(await fs.readFile(path.join(temp,'render-report.json')));
    assert.equal(report.research_used,false);
    assert.equal(report.expected_seconds,54);
    const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-of','json',path.join(temp,'output.mp4')],{encoding:'utf8'}));
    assert.ok(probe.streams.some(s=>s.codec_type==='audio'));
    assert.ok(probe.streams.some(s=>s.width===360&&s.height===640));
    assert.equal(await page.locator('#output').isVisible(),true);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    console.log('Browser integration passed: edit, subtitle shift, import, background MP4 export without Research, mobile layout.');
  } finally {
    if(browser)await browser.close();
    if(server){server.kill('SIGINT');await new Promise(r=>server.once('exit',r));}
    await fs.rm(temp,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
