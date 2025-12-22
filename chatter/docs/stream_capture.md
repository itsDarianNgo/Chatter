# Stream Capture (Host Publishers)

Milestone 4B adds host-run scripts to publish `StreamFrame` and `StreamTranscriptSegment` events into Redis for `stream_perceptor`.

These scripts:
- Write frames to disk under `data/stream_frames/...` (no binary blobs in Redis).
- Publish metadata-only events (path + sha + dims + timestamps).
- Validate payloads against the protocol JSON Schemas before publishing.

## Start the stack

From the repo root (`chatter/`):

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build
```

## Publish transcripts

### `stdin` mode (manual lines)

```bash
python scripts/capture/publish_transcripts.py --room-id room:demo --mode stdin
```

Type one line per segment (Ctrl+Z then Enter to end on Windows, Ctrl+D on macOS/Linux):

```text
E2E_TEST_STREAM_LIVE hello world!!!
```

### `tail` mode (follow a file)

```bash
python scripts/capture/publish_transcripts.py --room-id room:demo --mode tail --path data/transcripts/live.txt
```

Append lines to `data/transcripts/live.txt` from another shell/editor.

## Publish frames

### `file` mode (recommended fallback)

Republish the fixture image on a loop (writes into `data/stream_frames/...`):

```bash
python scripts/capture/publish_frames.py --room-id room:demo --mode file --file fixtures/stream/frame_fixture_1.png --interval-ms 2000
```

### `screen` mode (requires `mss`)

Install `mss` (local only):

```bash
pip install mss
```

Then:

```bash
python scripts/capture/publish_frames.py --room-id room:demo --mode screen --interval-ms 2000
```

## Verify the flow

### Check `stream_perceptor` stats

```bash
curl http://localhost:8100/stats
```

### Read the latest observation from Redis

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml exec redis redis-cli XREVRANGE stream:observations + - COUNT 1
```

### Inspect `stream_perceptor` logs

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml logs --tail=200 stream_perceptor
```

## Troubleshooting

- Missing `mss` (screen mode): `pip install mss`, or use `--mode file`.
- Missing `Pillow`: `publish_frames.py` can still publish PNGs without Pillow, but non-PNG inputs require `pip install pillow`.
- `file_missing` in `stream_perceptor /stats`: ensure frames are written under the repo (default `data/stream_frames/...`) and `frame_path` points to `/app/...` (compose bind-mounts the repo at `/app`).
- `sha_mismatch` in stats: the file at `frame_path` changed after publishing (overwritten, converted, or written to a different location than expected).

