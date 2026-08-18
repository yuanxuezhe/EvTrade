//! hqserverd 入口：编排 UDP 接收 -> Worker 池 -> WS 广播；统一信号处理。
//!
//! 等价于旧 hqserver.py: asyncio.run(main()) + signal handler。
//!
//! 退出语义：
//!   - 收到 SIGINT/SIGTERM -> 取消所有 task -> 关闭 UDP socket -> 关闭 WS server -> 退出
mod config;
mod types;
mod udp_receiver;
mod worker;
mod ws_server;

use std::sync::Arc;

use tokio::sync::mpsc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

use crate::config::Config;
use crate::udp_receiver::spawn as spawn_udp_rx;
use crate::worker::spawn_pool;
use crate::ws_server::{serve_ws, WsHub};

#[tokio::main]
async fn main() {
    // 初始化日志（默认 INFO；HQ_DEBUG=1 时手动 RUST_LOG=debug 即可）
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,debug"));
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .compact()
        .init();

    let cfg = Arc::new(Config::from_env());
    info!(?cfg, "[Boot] hqserverd 配置已加载");

    // 1. WS hub（与 UDP/Worker 都共享）
    let hub = WsHub::new();

    // 2. 内部 mpsc：UDP 接收 -> Worker 池（maxsize=cfg.max_queue_size，天然背压）
    let (tx, rx) = mpsc::channel::<Vec<u8>>(cfg.max_queue_size);

    // 3. UDP 接收 task
    let udp_handle = spawn_udp_rx(cfg.clone(), tx);

    // 4. WS server task
    let hub_for_ws = hub.clone();
    let cfg_for_ws = cfg.clone();
    let ws_handle = tokio::spawn(async move {
        serve_ws(&cfg_for_ws, hub_for_ws).await;
    });

    // 5. Worker pool
    let worker_handles = spawn_pool(cfg.clone(), hub.clone(), rx);

    // 6. 信号处理（跨平台：tokio::signal::ctrl_c 在 Windows/Linux/macOS 都可用）
    let stop = Arc::new(tokio::sync::Notify::new());
    {
        let stop = stop.clone();
        tokio::spawn(async move {
            // 在 Unix 系统上，SIGTERM 也通过 ctrl_c 监听不到；
            // 我们额外注册 signal::unix::signal 的特性 (tokio "signal" feature 已开)。
            #[cfg(unix)]
            {
                use tokio::signal::unix::{signal, SignalKind};
                let mut sigterm = match signal(SignalKind::terminate()) {
                    Ok(s) => s,
                    Err(e) => {
                        error!("[Signal] 注册 SIGTERM 失败: {e}");
                        return;
                    }
                };
                let mut sigint = match signal(SignalKind::interrupt()) {
                    Ok(s) => s,
                    Err(e) => {
                        error!("[Signal] 注册 SIGINT 失败: {e}");
                        return;
                    }
                };
                tokio::select! {
                    _ = sigterm.recv() => info!("[Signal] 收到 SIGTERM"),
                    _ = sigint.recv()  => info!("[Signal] 收到 SIGINT"),
                }
                stop.notify_waiters();
            }
            #[cfg(not(unix))]
            {
                if let Err(e) = tokio::signal::ctrl_c().await {
                    error!("[Signal] ctrl_c 失败: {e}");
                    return;
                }
                info!("[Signal] 收到 Ctrl+C");
                stop.notify_waiters();
            }
        });
    }

    info!("[Boot] hqserverd 已就绪：UDP={}, WS=ws://{}:{}",
        cfg.udp_bind, cfg.ws_host, cfg.ws_port);

    // 7. 主等待
    stop.notified().await;
    info!("[Shutdown] 开始优雅退出...");

    // 取消所有 task
    udp_handle.abort();
    ws_handle.abort();
    for h in worker_handles {
        h.abort();
    }

    info!("[Shutdown] hqserverd 已安全退出");
}