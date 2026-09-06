export type Asset = {
  id: string; kind: 'image' | 'video' | 'font'; path: string;
  creator: string; license: string; source: string; object_position: string;
};
export type Scene = {
  id: string; duration: number; narration: string; visual_intent: string;
  asset_refs: string[]; role: string; quote: string;
  subtitle: {start: number; end: number; text: string}[];
  audio: {path: string; offset: number; duration: number};
};
export type Board = {
  title: string; poem_title: string; author: string;
  width: number; height: number; fps: number;
  scenes: Scene[]; assets: Asset[];
};
export type Props = {board: Board};
