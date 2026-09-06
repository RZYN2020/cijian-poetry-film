import React, {useEffect, useState} from 'react';
import {
  AbsoluteFill, Audio, Composition, Img, OffthreadVideo, Sequence,
  cancelRender, continueRender, delayRender, interpolate, registerRoot, staticFile,
  useCurrentFrame, useVideoConfig,
} from 'remotion';
import type {Asset, Board, Props, Scene} from './types';

const serif = 'CiSerif, "Songti SC", "Noto Serif CJK SC", serif';
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

const Font: React.FC<{asset?: Asset}> = ({asset}) => {
  const [handle] = useState(() => delayRender('Load Chinese font'));
  useEffect(() => {
    if (!asset) {continueRender(handle); return;}
    const font = new FontFace('CiSerif', `url("${staticFile(asset.path)}")`);
    font.load().then((loaded) => {
      document.fonts.add(loaded); continueRender(handle);
    }).catch(cancelRender);
  }, [asset, handle]);
  return null;
};

const Shot: React.FC<{scene: Scene; asset: Asset; index: number}> = ({scene, asset, index}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const frames = Math.round(scene.duration * fps);
  const progress = frame / Math.max(1, frames - 1);
  const scale = interpolate(progress, [0, 1], index % 2 ? [1.055, 1.015] : [1.015, 1.055]);
  const opacity = interpolate(frame, [0, fps*.65, frames-fps*.65, frames-1], [0,1,1,0], clamp);
  const time = frame / fps;
  // Keep the single original line legible through the silence following its reading.
  const subtitle = scene.subtitle.find((c) => time >= c.start && time < c.end)
    ?? (time >= scene.subtitle[0].start ? scene.subtitle[scene.subtitle.length-1] : undefined);
  const textOpacity = interpolate(frame, [fps*.7, fps*1.3, frames-fps*1.2, frames-fps*.5], [0,1,1,0], clamp);
  const visualStyle: React.CSSProperties = {
    width:'100%', height:'100%', objectFit:'cover', objectPosition:asset.object_position,
    transform:`scale(${scale}) translateY(${Math.sin(progress*Math.PI)*-0.25}%)`,
  };
  return <AbsoluteFill style={{backgroundColor:'#1e2422'}}>
    <AbsoluteFill style={{opacity}}>
      {asset.kind === 'video'
        ? <OffthreadVideo src={staticFile(asset.path)} muted style={visualStyle} />
        : <Img src={staticFile(asset.path)} style={visualStyle} />}
      <AbsoluteFill style={{background:'linear-gradient(180deg, transparent 55%, rgba(15,23,23,.08) 70%, rgba(15,23,23,.40) 100%)'}} />
    </AbsoluteFill>
    <div style={{position:'absolute',bottom:height*.16,left:width*.07,right:width*.07,textAlign:'center',
      color:'#f2ebd9',fontFamily:serif,fontSize:width*.046,letterSpacing:width*.009,lineHeight:1.7,
      textShadow:'0 2px 15px rgba(0,0,0,.6)',opacity:textOpacity}}>
      {subtitle?.text}
    </div>
    <Sequence from={Math.round(scene.audio.offset*fps)}>
      <Audio src={staticFile(scene.audio.path)} volume={0.95} />
    </Sequence>
  </AbsoluteFill>;
};

const Music: React.FC<{board: Board}> = ({board}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const fadeFrames = Math.min(board.bgm_fade*fps, durationInFrames/2);
  const fade = Math.min(1, frame/fadeFrames, (durationInFrames-1-frame)/fadeFrames);
  let sceneStart = 0;
  let speech = 0;
  for (const scene of board.scenes) {
    const start = sceneStart + Math.round(scene.audio.offset*fps);
    const end = start + Math.ceil(scene.audio.duration*fps);
    // Smooth music attenuation around each recited line, then return to music.
    const duck = Math.max(0, Math.min(1,(frame-start+fps*.3)/(fps*.3),(end+fps*.8-frame)/(fps*.8)));
    speech = Math.max(speech,duck);
    sceneStart += Math.round(scene.duration*fps);
  }
  const volume = board.bgm_volume * Math.max(0,fade) * (1-speech*(1-board.bgm_duck));
  return board.bgm_path ? <Audio src={staticFile(board.bgm_path)} startFrom={Math.round(board.bgm_start*fps)} volume={volume}/> : null;
};

const Film: React.FC<Props> = ({board}) => {
  let start = 0;
  const assets = new Map(board.assets.map(a=>[a.id,a]));
  return <AbsoluteFill style={{backgroundColor:'#1e2422'}}>
    <Font asset={board.assets.find(a=>a.kind==='font')} />
    {board.scenes.map((scene,index)=>{
      const from=start;
      const durationInFrames=Math.round(scene.duration*board.fps);
      start+=durationInFrames;
      return <Sequence key={scene.id} from={from} durationInFrames={durationInFrames}>
        <Shot scene={scene} asset={assets.get(scene.asset_refs[0])!} index={index} />
      </Sequence>;
    })}
    <Music board={board}/>
  </AbsoluteFill>;
};

const defaults: Props = {board:{title:'',poem_title:'',author:'',width:1080,height:1920,fps:24,
  scenes:[],assets:[],bgm_volume:.16,bgm_start:0,bgm_fade:3,bgm_duck:.5}};
const Root: React.FC = () => <Composition
  id="PoetryFilm" component={Film} width={1080} height={1920} fps={24} durationInFrames={1440} defaultProps={defaults}
  calculateMetadata={({props})=>({width:props.board.width,height:props.board.height,fps:props.board.fps,
    durationInFrames:Math.max(1,props.board.scenes.reduce((n,s)=>n+Math.round(s.duration*props.board.fps),0))})}
/>;
registerRoot(Root);
