# recipe-box-rust

A standalone learning project: not yet called by the FastAPI backend, not
registered with Caddy, not in any Compose file. Scaffolding only.

## Run locally

```
cargo run
```

Starts an Axum server on port 8099 (override with `PORT=...`). Check it's up:

```
curl http://localhost:8099/health
```

## Why port 8099

The rest of this repo (`main.py`) picks free ports dynamically for the FastAPI
backend and Vite frontend, so there's no fixed port to collide with. 8099 is
just a stable default for running this service on its own while it has no
orchestration of its own yet.

## Docker

```
docker build -t recipe-box-rust .
docker run -p 8099:8099 recipe-box-rust
```

Not wired into any `docker-compose.yml` — this repo intentionally has none
(see `AGENTS.md`). If/when this service is ready to be called from the
Python backend, that integration (Caddy route, Compose file or native
process, calling convention) is a separate decision, not implied by this
scaffold.

## Next steps (not done yet)

- Pick one real slice of the app to reimplement (e.g. image storage, search)
  instead of growing this as a generic framework.
- Decide how the Python backend reaches it (HTTP call vs. something else).
- `Cargo.lock` isn't committed yet — run `cargo build` once and commit it
  (binaries, unlike libraries, should check in their lockfile).
