import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const project = path.resolve(process.argv[2] ?? 'projects/huanxisha');
const scaleIndex = process.argv.indexOf('--scale');
const scale = scaleIndex < 0 ? 1 : Number(process.argv[scaleIndex+1]);
if (!Number.isFinite(scale) || scale < .25 || scale > 1) throw new Error('scale must be between .25 and 1');
const stillIndex = process.argv.indexOf('--still');
// npm run render gets the same Pydantic, hash and path checks as the Python CLI.
const check = spawnSync('uv', ['run', 'ci-video', 'validate', project], {cwd:repo, stdio:'inherit'});
if (check.status !== 0) process.exit(check.status ?? 1);
const boardBytes = await fs.readFile(path.join(project, 'storyboard.json'));
const hash = (data) => createHash('sha256').update(data).digest('hex');
const boardHash = hash(boardBytes);
const board = JSON.parse(boardBytes);
const inputProps = {board};
const staging = path.join(project, '.render');
const publicDir = path.join(staging, 'public');
await fs.mkdir(publicDir, {recursive:true});
const usedIds = new Set(board.scenes.flatMap(s=>s.asset_refs));
const usedAssets = board.assets.filter(a=>usedIds.has(a.id)||a.kind==='font'||a.path===board.bgm_path);
const relativeFiles = [...usedAssets.map(a=>a.path), ...board.scenes.map(s=>s.audio.path)];
for (const file of new Set(relativeFiles)) {
  const to = path.join(publicDir, file);
  await fs.mkdir(path.dirname(to), {recursive:true});
  await fs.copyFile(path.join(project, file), to);
}
const serveUrl = await bundle({entryPoint:path.join(repo, 'renderer/index.tsx'), publicDir, outDir:path.join(staging,'bundle')});
const composition = await selectComposition({serveUrl, id:'PoetryFilm', inputProps});
if (stillIndex >= 0) {
  const frame = Number(process.argv[stillIndex+1]);
  await fs.mkdir(path.join(project,'qa'), {recursive:true});
  await renderStill({composition, serveUrl, inputProps, frame, scale, output:path.join(project,'qa',`frame-${frame}.png`)});
} else {
  let last = -1;
  const tempOutput = path.join(project, '.render', 'output.pending.mp4');
  await renderMedia({composition, serveUrl, inputProps, codec:'h264', audioCodec:'aac', pixelFormat:'yuv420p',
    outputLocation:tempOutput, scale, crf:19, concurrency:4, x264Preset:'fast',
    onProgress:({progress}) => {const p=Math.floor(progress*10)*10;if(p!==last){console.log(`Render ${p}%`);last=p;}}
  });
  if (hash(await fs.readFile(path.join(project,'storyboard.json'))) !== boardHash) throw new Error('Storyboard changed during render; output not published');
  const probe = spawnSync('ffprobe',['-v','error','-show_format','-show_streams','-of','json',tempOutput],{encoding:'utf8'});
  if (probe.status !== 0) throw new Error('Could not probe completed video');
  const metadata = JSON.parse(probe.stdout);
  const expected = composition.durationInFrames/composition.fps;
  if (Math.abs(Number(metadata.format.duration)-expected)>.15 || !metadata.streams.some(s=>s.codec_type==='audio')) throw new Error('Output duration/audio validation failed');
  const outputBytes = await fs.readFile(tempOutput);
  const report = {created_at:new Date().toISOString(),storyboard_sha256:boardHash,output_sha256:hash(outputBytes),
    expected_seconds:expected,actual_seconds:Number(metadata.format.duration),narration:board.scenes.map(s=>s.narration).join(''),
    tts_providers:[...new Set(board.scenes.map(s=>s.audio.provider))],bgm:usedAssets.find(a=>a.path===board.bgm_path)??null,
    assets:usedAssets.map(a=>({id:a.id,sha256:a.sha256,generation:a.generation??null})),probe:metadata,research_used:false,llm_used:false};
  const credits = spawnSync('uv',['run','ci-video','credits',project],{cwd:repo,stdio:'inherit'});
  if(credits.status!==0) throw new Error('Could not write credits');
  await fs.rename(tempOutput, path.join(project, 'output.mp4'));
  await fs.writeFile(path.join(project,'rendered-storyboard.json'),boardBytes);
  await fs.writeFile(path.join(project,'render-report.json'),JSON.stringify(report,null,2)+'\n');
}
