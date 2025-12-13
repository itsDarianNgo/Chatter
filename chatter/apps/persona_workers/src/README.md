# persona_workers/src

Python package entrypoint(s) and worker runtime.

## Layout
- `persona_workers/` (python package) contains worker logic
- `main.py` (entrypoint) wires config + starts runner

Keep worker logic modular so we can scale to many agents per process or per pod.
