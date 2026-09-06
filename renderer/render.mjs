import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const project = path.resolve(process.argv[2] ?? 'projects/huanxisha');
const scale = Number(process.argv[process.argv.indexOf('--scale')+1]) || 1;
const stillIndex = process.argv.indexOf('--still');
// npm run render gets the same Pydantic, hash and path checks as the Python CLI.
const check = spawnSync('uv', ['run', 'ci-video', 'validate', project], {cwd:repo, stdio:'inherit'});
if (check.status !== 0) process.exit(check.status ?? 1);
const board = JSON.parse(await fs.readFile(path.join(project, 'storyboard.json'), 'utf8'));
const inputProps = {board};
const staging = path.join(project, '.render');
const publicDir = path.join(staging, 'public');
await fs.mkdir(publicDir, {recursive:true});
const relativeFiles = [...board.assets.map(a=>a.path), ...board.scenes.map(s=>s.audio.path), ...(board.bgm_path ? [board.bgm_path] : [])];
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
  await fs.rename(tempOutput, path.join(project, 'output.mp4'));
}
