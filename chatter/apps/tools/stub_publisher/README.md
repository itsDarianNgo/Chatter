# Stub Publisher

Generates valid `ChatMessage` payloads and publishes them to `stream:chat.ingest` for load testing.

## Usage
```
python apps/tools/stub_publisher/publish.py --rate 20 --users 25 --duration 60
```

Key options:
- `--redis-url` (default `redis://localhost:6379/0`)
- `--room-id` (default `room:demo`)
- `--rate` messages per second (float)
- `--users` number of simulated users
- `--duration` seconds to run (0 = forever)
- `--mode` `random` or `burst`
- `--burst-size` messages per burst when mode=`burst`
