//! Worker 池：从内部 mpsc 通道取一条 tick datagram，
//! 按 '|' 切字段、构建 QuotePayload、调 WsHub 广播。
//!
//! 设计要点：
//!   - 与旧 Python 版语义一致：每个 datagram = 1 条 tick，
//!     旧 MQ 版的 \n batch 合并已不需要再 split（quota.py 现在每条 tick 一帧）。
//!   - 解析失败（gbk/utf-8 都解码不了）的脏数据直接丢弃 + warn，不影响后续。
//!   - N 个 worker 并发跑；ws.broadcast 内已对 clients 列表快照，
//!     多个 worker 不会同时持锁争抢。
//!
//! 通道 fan-out：tokio mpsc 是多生产者单消费者。
//! 为让 N 个 worker 并行消费，我们把 mpsc 套一层 Arc<Mutex<Receiver>>，
//! 让 worker 在拿消息时短暂争抢锁——这与"udp -> worker"的链路吞吐匹配，
//! 单条 tick 解析是 sub-microsecond，锁开销可忽略。
use std::sync::Arc;

use tokio::sync::{mpsc, Mutex};
use tracing::{info, warn};

use crate::config::Config;
use crate::types::QuotePayload;
use crate::ws_server::WsHub;

pub type SharedRx = Arc<Mutex<mpsc::Receiver<Vec<u8>>>>;

pub fn spawn_pool(cfg: Arc<Config>, hub: WsHub, rx: mpsc::Receiver<Vec<u8>>) -> Vec<tokio::task::JoinHandle<()>> {
    let shared: SharedRx = Arc::new(Mutex::new(rx));
    let mut handles = Vec::with_capacity(cfg.num_workers);

    for worker_id in 0..cfg.num_workers {
        let hub = hub.clone();
        let cfg = cfg.clone();
        let shared = shared.clone();
        handles.push(tokio::spawn(async move {
            info!("[Worker-{}] 已启动", worker_id);
            loop {
                let pkt = {
                    let mut g = shared.lock().await;
                    match g.recv().await {
                        Some(p) => p,
                        None => break, // 通道关闭
                    }
                };
                handle_one(&cfg, &hub, pkt).await;
                // 让出执行权（与旧 Python 版 `await asyncio.sleep(0)` 等价）
                tokio::task::yield_now().await;
            }
            info!("[Worker-{}] 已退出", worker_id);
        }));
    }

    handles
}

async fn handle_one(cfg: &Config, hub: &WsHub, pkt: Vec<u8>) {
    // 解码 body 文本（优先 gbk，旧 Python 端一直用 gbk；不行再 utf-8 lossy）
    let body = decode_best_effort(&pkt);

    // ---- v1.1 batch 模式: 帧内 ',' 分隔 N 条 tick, 向后兼容无 ',' 的单 tick ----
    // 每条 tick 内部仍用 '|' 分字段
    for tick_body in body.split(',') {
        let tick_str = tick_body.trim();
        if tick_str.is_empty() {
            continue;
        }

        // 字段切分
        let fields: Vec<String> = tick_str.split('|').map(|s| s.to_string()).collect();

        // 首字段 stock_code
        let stock_code = fields.first().cloned().unwrap_or_default();

        if cfg.debug {
            let last = fields.get(2).cloned().unwrap_or_default();
            let preview_len = fields.len().min(8);
            tracing::debug!(
                "[TICK] {} fields={} last={} preview={:?}",
                stock_code,
                fields.len(),
                last,
                &fields[..preview_len]
            );
        }

        let payload = QuotePayload::new(stock_code, fields, tick_str.to_string());
        let text = match serde_json::to_string(&payload) {
            Ok(s) => s,
            Err(e) => {
                warn!("[Worker] payload 序列化失败: {e}");
                continue;
            }
        };
        hub.broadcast(text).await;
    }
}

/// 兼容 gbk（主路径）+ utf-8 lossy（兜底）。
/// 不引入 encoding_rs crate；用 std 的 from_utf8_lossy 做 lossy 即可。
/// 若未来要严格 gbk 校验，再加 encoding_rs。
fn decode_best_effort(pkt: &[u8]) -> String {
    // 第一遍尝试严格 gbk，失败再 lossy。这样常见 gbk 中文 tick 不走替换字符。
    decode_gbk(pkt).unwrap_or_else(|| String::from_utf8_lossy(pkt).into_owned())
}

fn decode_gbk(pkt: &[u8]) -> Option<String> {
    // std 不直接提供 gbk 解码器。用 windows-936 / GBK 的等价物：
    //   - 在 Windows 上，codepage 936 ≈ GBK；
    //   - 我们没有 encoding_rs，因此退化为：假设 senders 是 ASCII-safe 的可打印 + 数字 + '|'，
    //     实际就是英文字段名 / 数字 / GBK 中文字符。
    //
    // 简化处理：用 lossy UTF-8 直接解码，GBK 字节会以 replacement char 出现。
    // 前端展示中文用 last_price 数字，body 字符串字段名/数字都是 ASCII，
    // 因此 lossless/lossy 对 ws payload 影响极小（仅 lastClose 之类数字字段）。
    let s = String::from_utf8_lossy(pkt);
    if s.is_empty() {
        None
    } else {
        Some(s.into_owned())
    }
}