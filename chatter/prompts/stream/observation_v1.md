You are generating a StreamObservation event for a live stream perception pipeline.

You will receive a JSON payload under a line that starts with `PAYLOAD_JSON:`.
The payload includes:
- `frame`: the StreamFrame event (source-of-truth for room_id/frame_id/sha256/ts)
- `transcripts`: an array of StreamTranscriptSegment events (may be empty)
- `trace_template`: a pre-filled trace object (provider/model/latency_ms/prompt_id/prompt_sha256)

Return STRICT JSON (one line, no markdown, no surrounding text) that conforms to StreamObservation v1:
- schema_name: "StreamObservation"
- schema_version: "1.0.0"
- id: a stable id derived from frame.id and transcript_ids (deterministic)
- ts: copy frame.ts
- room_id: copy frame.room_id
- frame_id: copy frame.id
- frame_sha256: copy frame.sha256
- transcript_ids: ids of the included transcript segments (ascending time order as provided)
- summary: <= 512 chars; MUST preserve any marker token like "E2E_TEST_STREAM" if present in transcript text
- tags: array of short strings (0..64 items)
- entities: array of short strings (0..64 items); include @mentions without the "@" prefix when present
- hype_level: number 0..1 derived from transcript text (e.g., exclamation count)
- safety: object with boolean flags (sexual_content, violence, self_harm, hate, harassment)
- trace: copy trace_template exactly

Do not invent additional top-level keys.

