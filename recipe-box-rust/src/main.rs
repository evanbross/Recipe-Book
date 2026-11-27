// =============================================================================
// Copyright (c) 2026 ZombieTech LLC. All rights reserved.
//
// SPDX-License-Identifier: PolyForm-Strict-1.0.0
// See LICENSE in the project root for the full terms.
//
// Licensing inquiries: license@zombietech.biz
// =============================================================================

//! Standalone learning service, not yet wired into the FastAPI backend or Caddy.
//! Run with `cargo run`; defaults to port 8099 (see README.md for why that port).

use std::net::SocketAddr;

use axum::{routing::get, Json, Router};
use serde_json::{json, Value};
use tokio::signal;

const DEFAULT_PORT: u16 = 8099;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_target(true)
        .with_file(true)
        .with_line_number(true)
        .init();

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .unwrap_or(DEFAULT_PORT);

    let app = Router::new().route("/health", get(health));

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .unwrap_or_else(|err| panic!("could not bind to {addr}: {err}"));

    tracing::info!("recipe-box-rust listening on http://{addr}");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap_or_else(|err| panic!("server error: {err}"));
}

async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

async fn shutdown_signal() {
    signal::ctrl_c()
        .await
        .expect("failed to listen for ctrl-c");
    tracing::info!("shutdown signal received");
}
