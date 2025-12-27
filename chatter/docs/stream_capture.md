# Stream Capture (Host Publishers)

Milestone 4B adds host-run scripts to publish `StreamFrame` and `StreamTranscriptSegment` events into Redis for `stream_perceptor`.

These scripts:
- Write frames to disk under `data/stream_frames/...` (no binary blobs in Redis).
- Publish metadata-only events (path + sha + dims + timestamps).
- Validate payloads against the protocol JSON Schemas before publishing.

## Local stream demo (Milestone 4F)

### Prereqs

Host publishers require:

```bash
pip install redis jsonschema python-dotenv
```

Optional (recommended for screen capture + non-PNG conversion):

```bash
pip install mss pillow
```

Recommended `.env` for host runs:

```bash
REDIS_URL_HOST=redis://127.0.0.1:6379/0
```

### One-command demo

From the repo root (`chatter/`):

```bash
npm run dev:stream
```

On Windows, `npm run dev:stream` expects Git Bash on PATH. For PowerShell, use the command below.

Git Bash alternative:

```bash
bash scripts/dev/run_stream_demo.sh
```

PowerShell alternative:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/run_stream_demo.ps1
```

Type transcript lines and watch observations print in the same terminal. Use Ctrl+C to stop.

### Autonomous commentary demo (Milestone 4G)

Enable autonomous bot commentary during the stream demo:

```bash
AUTO_COMMENTARY_ENABLED=1 npm run dev:stream
```

Tune thresholds/cooldowns by editing `configs/auto_commentary/default.json` or pointing
`AUTO_COMMENTARY_CONFIG_PATH` at another config file.

### Tail observations only

```bash
npm run dev:tail:observations
```

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
- Redis hostname resolution on host: ensure `REDIS_URL_HOST=redis://127.0.0.1:6379/0` is set (host scripts should not use `redis://redis:6379/0`).
- Inspect observations directly: `docker compose -f docker-compose.yml -f docker-compose.test.yml exec redis redis-cli XREVRANGE stream:observations + - COUNT 5`.
- `file_missing` in `stream_perceptor /stats`: ensure frames are written under the repo (default `data/stream_frames/...`) and `frame_path` points to `/app/...` (compose bind-mounts the repo at `/app`).
- `sha_mismatch` in stats: the file at `frame_path` changed after publishing (overwritten, converted, or written to a different location than expected).
