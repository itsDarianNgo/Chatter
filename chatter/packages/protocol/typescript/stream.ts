export type SemverString = `${number}.${number}.${number}`;

export type StreamFrameFormat = "png" | "jpg" | "jpeg" | "webp";

export interface StreamFrameV1 {
  schema_name: "StreamFrame";
  schema_version: SemverString;
  id: string;
  ts: string;
  room_id: string;
  frame_path: string;
  sha256: string;
  width: number;
  height: number;
  format: StreamFrameFormat;
  source: string;
  seq: number;
  capture_ms?: number;
  meta?: Record<string, unknown> | null;
}

export interface StreamTranscriptSegmentV1 {
  schema_name: "StreamTranscriptSegment";
  schema_version: SemverString;
  id: string;
  ts: string;
  room_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  confidence?: number;
  meta?: Record<string, unknown> | null;
}

export interface StreamObservationSafetyV1 {
  sexual_content: boolean;
  violence: boolean;
  self_harm: boolean;
  hate: boolean;
  harassment: boolean;
}

export interface StreamObservationTraceV1 {
  provider: string;
  model: string;
  latency_ms: number;
  prompt_id: string;
  prompt_sha256: string;
  [key: string]: unknown;
}

export interface StreamObservationV1 {
  schema_name: "StreamObservation";
  schema_version: SemverString;
  id: string;
  ts: string;
  room_id: string;
  frame_id: string;
  frame_sha256: string;
  transcript_ids: string[];
  summary: string;
  tags: string[];
  entities: string[];
  hype_level: number;
  safety: StreamObservationSafetyV1;
  trace: StreamObservationTraceV1;
  meta?: Record<string, unknown> | null;
}

