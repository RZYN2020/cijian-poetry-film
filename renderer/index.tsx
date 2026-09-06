import React, {useEffect, useState} from 'react';
import {
  AbsoluteFill, Audio, Composition, Img, OffthreadVideo, Sequence,
  continueRender, delayRender, interpolate, registerRoot, staticFile,
  useCurrentFrame, useVideoConfig,
} from 'remotion';
import type {Asset, Board, Props, Scene} from './types';

const ink = '#eee9dd';
const serif = 'CiSerif, "Songti SC", "Noto Serif CJK SC", serif';

const Font: React.FC<{asset?: Asset}> = ({asset}) => {
  const [handle] = useState(() => delayRender('Load Chinese font'));
  useEffect(() => {
    if (!asset) {continueRender(handle); return;}
    const font = new FontFace('CiSerif', `url("${staticFile(asset.path)}")`);
    font.load().then((loaded) => {
      document.fonts.add(loaded); continueRender(handle);
    }).catch((error) => {throw error;});
  }, [asset, handle]);
  return null;
};

const Shot: React.FC<{scene: Scene; asset: Asset; index: number; count: number; board: Board}> = ({scene, asset, index, count, board}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const frames = Math.round(scene.duration * fps);
  const progress = frame / Math.max(1, frames - 1);
  const scale = interpolate(progress, [0, 1], index % 2 ? [1.065, 1.015] : [1.015, 1.065]);
  const opacity = interpolate(frame, [0, 12, frames - 12, frames - 1], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const time = frame / fps;
  const caption = scene.subtitle.find((c) => time >= c.start && time < c.end);
  const isPoem = Boolean(scene.quote);
  const fontSize = width * 0.039;
  const visualStyle: React.CSSProperties = {
    width: '100%', height: '100%', objectFit: 'cover', objectPosition: asset.object_position,
    transform: `scale(${scale})`, filter: 'saturate(0.58) brightness(0.73)',
  };
  return <AbsoluteFill style={{backgroundColor: '#111817', color: ink}}>
    <AbsoluteFill style={{opacity}}>
      {asset.kind === 'video'
        ? <OffthreadVideo src={staticFile(asset.path)} muted style={visualStyle} />
        : <Img src={staticFile(asset.path)} style={visualStyle} />}
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(7,18,17,.25) 0%, transparent 35%, rgba(7,13,12,.28) 60%, rgba(7,13,12,.91) 100%)'}} />
    </AbsoluteFill>
    <div style={{position: 'absolute', top: height * .055, left: width * .085, right: width * .085, display: 'flex', justifyContent: 'space-between', fontFamily: serif, fontSize: width * .022, letterSpacing: width * .005, opacity: .67}}>
      <span>旧时天气</span><span>词与今日 · 壹</span>
    </div>
    {index === 0 ? <div style={{position: 'absolute', top: height * .17, left: width * .085, opacity: interpolate(frame, [8, 30, frames-20, frames-1], [0,1,1,0], {extrapolateLeft:'clamp', extrapolateRight:'clamp'})}}>
      <div style={{fontFamily: serif, fontSize: width * .068, letterSpacing: width * .009, lineHeight: 1.5}}>{board.title}</div>
      <div style={{marginTop: 22, fontFamily: serif, fontSize: width * .024, opacity: .72, letterSpacing: 5}}>一首词，留住一个瞬间</div>
    </div> : null}
    <div style={{position: 'absolute', bottom: height * .164, left: width * .07, right: width * .07, textAlign: 'center', minHeight: height * .085, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end'}}>
      {caption ? <div style={{fontFamily: serif, fontWeight: 400, fontSize: isPoem ? fontSize * 1.18 : fontSize, lineHeight: 1.7, letterSpacing: width * .003, whiteSpace: 'pre-line', textShadow: '0 2px 14px #000'}}>{caption.text}</div> : null}
      {isPoem ? <div style={{fontFamily: serif, fontSize: width * .021, marginTop: height * .015, letterSpacing: 4, opacity: .66}}>晏殊 · 浣溪沙</div> : null}
    </div>
    <div style={{position:'absolute', left:width*.085, right:width*.085, bottom:height*.093, height:1, background:'rgba(233,228,209,.20)'}} />
    <div style={{position: 'absolute', bottom: height * .057, left: width * .085, right: width * .085, display: 'flex', justifyContent: 'space-between', gap: 24, alignItems: 'flex-end', fontFamily: 'sans-serif', fontSize: width * .015, lineHeight: 1.5, opacity: .62}}>
      <span style={{maxWidth:'86%'}}>图像 · {asset.creator} · {asset.license}<br/>裁剪、调色、缓慢推移 · 完整来源见 credits.md</span>
      <span>{String(index + 1).padStart(2,'0')} / {String(count).padStart(2,'0')}</span>
    </div>
    <Sequence from={Math.round(scene.audio.offset * fps)}>
      <Audio src={staticFile(scene.audio.path)} volume={1} />
    </Sequence>
  </AbsoluteFill>;
};

const Film: React.FC<Props> = ({board}) => {
  let start = 0;
  const assets = new Map(board.assets.map(a => [a.id, a]));
  return <AbsoluteFill style={{backgroundColor:'#111817'}}>
    <Font asset={board.assets.find(a => a.kind === 'font')} />
    {board.scenes.map((scene, index) => {
      const from = start;
      const durationInFrames = Math.round(scene.duration * board.fps);
      start += durationInFrames;
      return <Sequence key={scene.id} from={from} durationInFrames={durationInFrames}>
        <Shot scene={scene} asset={assets.get(scene.asset_refs[0])!} index={index} count={board.scenes.length} board={board} />
      </Sequence>;
    })}
    {board.bgm_path ? <Audio src={staticFile(board.bgm_path)} volume={board.bgm_volume ?? 0.12} loop /> : null}
  </AbsoluteFill>;
};

const Root: React.FC = () => <Composition<any, Props>
  id="PoetryFilm" component={Film} width={1080} height={1920} fps={24} durationInFrames={1440} defaultProps={{board: {title:'',poem_title:'',author:'',width:1080,height:1920,fps:24,scenes:[],assets:[]}}}
  calculateMetadata={({props}) => ({width:props.board.width, height:props.board.height, fps:props.board.fps, durationInFrames:props.board.scenes.reduce((n,s)=>n+Math.round(s.duration*props.board.fps),0)})}
/>;
registerRoot(Root);
