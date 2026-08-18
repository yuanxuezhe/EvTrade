//! UDP 接收器：绑定 UDP socket，把每个 datagram 当成一条完整 tick 推入内部有界 mpsc。
//!
//! 协议：
//!   - 单条 tick = 一帧 UDP datagram（每帧 ≤ MTU ~1500B，远大于一条 tick ~200B）
//!   - 字段 '|' 分隔，首字段 stock_code（gbk 编码）
//!   - 不做 ACK / 不做重传（行情丢一两条无所谓）
//!
//! 内部缓冲：tokio mpsc channel(maxsize=max_queue_size)，背压时 send 阻塞，
//! 等同于旧 asyncio.Queue 天然背压的语义。
use std::net::SocketAddr;
use std::sync::Arc;

use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

use crate::config::Config;

pub fn spawn(cfg: Arc<Config>, tx: mpsc::Sender<Vec<u8>>) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let sock = match UdpSocket::bind(&cfg.udp_bind).await {
            Ok(s) => s,
            Err(e) => {
                warn!("[UDP] 绑定 {} 失败: {e}", cfg.udp_bind);
                return;
            }
        };
        info!(
            "[UDP] 已绑定 {}（等待 quota.py 从 {} 推送）",
            cfg.udp_bind, cfg.udp_peer
        );

        let mut buf = vec![0u8; 64 * 1024];
        loop {
            match sock.recv_from(&mut buf).await {
                Ok((n, peer)) => {
                    let pkt = buf[..n].to_vec();
                    if cfg.debug {
                        debug!("[UDP] recv {}B from {}", n, peer);
                    }
                    // 背压：若 worker 还没把上一帧消化掉，这里会 await
                    if tx.send(pkt).await.is_err() {
                        warn!("[UDP] worker 通道已关闭，UDP 接收退出");
                        return;
                    }
                    let _ = peer; // unused but logged above in debug
                    let _ = SocketAddr::from(peer);
                }
                Err(e) => {
                    warn!("[UDP] recv_from 错误: {e}");
                    // 短暂退避
                    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                }
            }
        }
    })
}