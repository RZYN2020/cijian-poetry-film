from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

Text = Annotated[str, Field(min_length=1)]
Stage = Literal["modern_moment", "emotion", "poem_enters", "context", "rereading", "return_today"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Brief(Model):
    poem_title: Text
    author: Text
    poem_text: Text
    emotion: Text
    modern_moment: Text
    target_seconds: float = Field(default=60, ge=30, le=120)
    tone: list[str] = ["克制", "安静", "含蓄", "有记忆感"]
    avoid: list[str] = ["鸡汤", "营销", "过度煽情", "作者介绍开场", "虚构作者生平"]


class Source(Model):
    id: Text
    title: Text
    url: Text
    creator: Text
    accessed_at: Text
    kind: Literal["primary_text", "institutional_reference", "scholarly_reference"]
    excerpt: Text
    locator: Text
    rights_note: Text


class Evidence(Model):
    id: Text
    source_id: Text
    quote: Text
    locator: Text


class Claim(Model):
    id: Text
    text: Text
    kind: Literal["fact", "interpretation"]
    evidence_ids: list[str] = Field(min_length=1)
    confidence_note: Text


def unique(items, name):
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {name} id")


class ResearchPack(Model):
    schema_version: Literal["1.0"] = "1.0"
    poem_title: Text
    author: Text
    original_text: Text
    sources: list[Source] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    textual_notes: list[str]
    unknowns: list[str]
    provenance: Text
    review_status: Literal["source_checked", "needs_review"]

    @model_validator(mode="after")
    def links(self):
        for seq, name in [(self.sources, "source"), (self.evidence, "evidence"), (self.claims, "claim")]:
            unique(seq, name)
        sources = {s.id: s for s in self.sources}
        evidence = {e.id for e in self.evidence}
        for e in self.evidence:
            if e.source_id not in sources or e.quote not in sources[e.source_id].excerpt:
                raise ValueError(f"evidence {e.id}: quote must occur verbatim in its source excerpt")
        for c in self.claims:
            if not set(c.evidence_ids) <= evidence:
                raise ValueError(f"claim {c.id}: unknown evidence")
        return self


class Beat(Model):
    id: Text
    role: Stage
    narration: Text
    subtitle_lines: list[Text] = Field(min_length=1)
    visual_intent: Text
    asset_hint: Text
    claim_ids: list[str]
    quote: str = ""
    editorial_note: str = ""


class Script(Model):
    schema_version: Literal["1.0"] = "1.0"
    title: Text
    emotional_thesis: Text
    provenance: Text
    beats: list[Beat] = Field(min_length=6, max_length=10)

    @model_validator(mode="after")
    def structure(self):
        unique(self.beats, "beat")
        roles = [b.role for b in self.beats]
        expected = ["modern_moment", "emotion", "poem_enters", "context", "rereading", "return_today"]
        collapsed = [r for i, r in enumerate(roles) if i == 0 or r != roles[i-1]]
        if collapsed != expected:
            raise ValueError(f"narrative arc must be {expected}")
        return self


def safe_relative(value: str) -> str:
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or "\\" in value or ":" in value:
        raise ValueError("path must stay inside the project")
    return value


class Asset(Model):
    id: Text
    kind: Literal["image", "video", "font"]
    path: Text
    source: Text
    creator: Text
    license: Text
    license_url: str = ""
    download_url: str = ""
    sha256: str = ""
    description: Text
    object_position: str = "50% 50%"
    _path = field_validator("path")(safe_relative)


class Subtitle(Model):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: Text


class NarrationAudio(Model):
    path: Text
    text_sha256: Text
    file_sha256: Text
    duration: float = Field(gt=0)
    offset: float = Field(default=0.35, ge=0)
    provider: Text
    voice: Text
    rate: Text
    timing_method: Literal["tts_boundaries", "estimated", "manual"]
    _path = field_validator("path")(safe_relative)


class Scene(Model):
    id: Text
    duration: float = Field(gt=0, le=30)
    narration: Text
    subtitle: list[Subtitle] = Field(min_length=1)
    visual_intent: Text
    asset_refs: list[str] = Field(min_length=1, max_length=1)
    claim_ids: list[str] = []
    role: Stage
    quote: str = ""
    audio: NarrationAudio | None = None

    @model_validator(mode="after")
    def timing(self):
        last = 0
        for sub in self.subtitle:
            if sub.start < last - 1e-6 or sub.end <= sub.start or sub.end > self.duration + 1e-6:
                raise ValueError(f"scene {self.id}: overlapping or out-of-scene subtitle")
            last = sub.end
        if self.audio and self.audio.offset + self.audio.duration > self.duration + 1e-6:
            raise ValueError(f"scene {self.id}: speech exceeds scene; run tts --fit or extend duration")
        return self


class Storyboard(Model):
    schema_version: Literal["1.0"] = "1.0"
    project_id: Text
    title: Text
    poem_title: Text
    author: Text
    width: int = Field(default=1080, ge=360, le=3840)
    height: int = Field(default=1920, ge=360, le=3840)
    fps: int = Field(default=24, ge=12, le=60)
    assets: list[Asset] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=6, max_length=10)

    @model_validator(mode="after")
    def references(self):
        unique(self.assets, "asset")
        unique(self.scenes, "scene")
        assets = {a.id: a for a in self.assets}
        if self.width % 2 or self.height % 2:
            raise ValueError("h264 output dimensions must be even")
        for s in self.scenes:
            if not set(s.asset_refs) <= assets.keys():
                raise ValueError(f"scene {s.id}: unknown asset")
            if any(assets[a].kind == "font" for a in s.asset_refs):
                raise ValueError("font cannot be used as scene image")
            if not math.isclose(s.duration * self.fps, round(s.duration * self.fps), abs_tol=1e-5):
                raise ValueError(f"scene {s.id}: duration must be a multiple of 1/fps")
        return self


class ContentProject(Model):
    schema_version: Literal["1.0"] = "1.0"
    id: Text
    brief: Brief
    research: str = "research.json"
    script: str = "script.json"
    storyboard: str = "storyboard.json"
    output: str = "output.mp4"
    created_at: Text
