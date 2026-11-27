# syntax=docker/dockerfile:1

FROM rust:1-slim AS builder
WORKDIR /app

# Cache dependency compilation separately from source changes: build a dummy
# main.rs against just the manifest first, so editing src/ doesn't re-fetch/
# re-build every crate.
COPY Cargo.toml Cargo.lock* ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release && rm -rf src

COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/recipe-box-rust ./recipe-box-rust

ENV PORT=8099
EXPOSE 8099
CMD ["./recipe-box-rust"]
