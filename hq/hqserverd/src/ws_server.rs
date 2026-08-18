//! WebSocket 服务：注册/注销客户端、对所有客户端广播 tick payload。
//!
//! 协议保持兼容旧 hqserver.py：
//!   - 路径任意（前端只用默认 /）
//!   - 客户端不发业务消息，仅 keepalive
//!   - 等价旧版 ping_interval=15s / ping_timeout=60s：
//!     tokio-tungstenite 0.24 的 WebSocketConfig 没有 ping_interval 字段，
//!     我们用上层 tokio::time::interval 每 15s 主动 Ping 客户端。
//!     客户端 60s 内未响应 Pong 视为掉线（tungstenite 默认 timeout）。
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::tungstenite::Message;
use tracing::{error, info, warn};

use crate::config::Config;

pub type WsTx = mpsc::UnboundedSender<Message>;

#[derive(Clone)]
pub struct WsHub {
    inner: Arc<Mutex<WsHubInner>>,
}

struct WsHubInner {
    /// peer -> sender
    clients: HashMap<SocketAddr, WsTx>,
}

impl WsHub {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(WsHubInner {
                clients: HashMap::new(),
            })),
        }
    }

    /// 给所有当前客户端广播一条文本帧。
    /// 失败/掉线客户端会被动清理。
    pub async fn broadcast(&self, text: String) {
        let msg = Message::Text(text);

        // 先快照出当前客户端列表，避免持锁 await send
        let snapshot: Vec<(SocketAddr, WsTx)> = {
            let g = self.inner.lock().await;
            g.clients.iter().map(|(k, v)| (*k, v.clone())).collect()
        };

        let mut dead: Vec<SocketAddr> = Vec::new();
        for (peer, tx) in snapshot {
            if tx.send(msg.clone()).is_err() {
                dead.push(peer);
            }
        }

        if !dead.is_empty() {
            let mut g = self.inner.lock().await;
            for peer in dead {
                g.clients.remove(&peer);
            }
        }
    }

    async fn add(&self, peer: SocketAddr, tx: WsTx) {
        let mut g = self.inner.lock().await;
        g.clients.insert(peer, tx);
        info!(clients = g.clients.len(), "[WS] 客户端已连接");
    }

    async fn remove(&self, peer: &SocketAddr) {
        let mut g = self.inner.lock().await;
        g.clients.remove(peer);
        info!(clients = g.clients.len(), "[WS] 客户端已断开");
    }
}

pub async fn serve_ws(cfg: &Config, hub: WsHub) {
    let addr = format!("{}:{}", cfg.ws_host, cfg.ws_port);
    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            error!("[WS] 绑定 {addr} 失败: {e}");
            return;
        }
    };
    info!("[WS] 已监听 ws://{addr}（与旧 hqserver.py 等价）");

    loop {
        let (stream, peer) = match listener.accept().await {
            Ok(v) => v,
            Err(e) => {
                error!("[WS] accept 错误: {e}");
                continue;
            }
        };

        let ws_stream = match tokio_tungstenite::accept_async(stream).await {
            Ok(s) => s,
            Err(e) => {
                error!("[WS] 升级握手失败 {peer}: {e}");
                continue;
            }
        };

        let hub_for_conn = hub.clone();
        tokio::spawn(async move {
            handle_ws_conn(ws_stream, peer, hub_for_conn).await;
        });
    }
}

async fn handle_ws_conn<S>(ws: S, peer: SocketAddr, hub: WsHub)
where
    S: futures_util::Stream<Item = Result<Message, tokio_tungstenite::tungstenite::Error>>
        + futures_util::Sink<Message, Error = tokio_tungstenite::tungstenite::Error>
        + Unpin
        + Send
        + 'static,
{
    let (tx, mut rx) = mpsc::unbounded_channel::<Message>();
    hub.add(peer, tx.clone()).await;

    let (mut sink, mut stream) = ws.split();

    // 出站 task：把广播进来的消息写到 socket；每 15s 主动 Ping 一次（等价旧版 ping_interval=15）
    let out = tokio::spawn(async move {
        let mut ping_interval = tokio::time::interval(Duration::from_secs(15));
        ping_interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                msg = rx.recv() => {
                    match msg {
                        Some(m) => {
                            if sink.send(m).await.is_err() {
                                break;
                            }
                        }
                        None => break,
                    }
                }
                _ = ping_interval.tick() => {
                    if sink.send(Message::Ping(Vec::new())).await.is_err() {
                        break;
                    }
                }
            }
        }
    });

    // 入站 task：仅用于探测断开（客户端不发业务消息，但要回应 Pong）
    while let Some(msg) = stream.next().await {
        match msg {
            Ok(Message::Close(_)) => break,
            Ok(Message::Pong(_)) => continue,
            Ok(_) => continue,
            Err(e) => {
                warn!("[WS] {peer} 错误: {e}");
                break;
            }
        }
    }

    hub.remove(&peer).await;
    out.abort();
}