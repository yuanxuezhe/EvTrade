//! 环境变量配置（取代旧 hqserver.py 顶部的 _env_* 一组函数）
use std::env;

fn env_or(key: &str, default: &str) -> String {
    env::var(key)
        .ok()
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| default.to_string())
}

fn env_int(key: &str, default: i64) -> i64 {
    env_or(key, &default.to_string())
        .parse()
        .unwrap_or(default)
}

fn env_bool(key: &str, default: bool) -> bool {
    let v = env_or(key, &default.to_string());
    matches!(v.to_lowercase().as_str(), "1" | "true" | "yes" | "on")
}

#[derive(Debug, Clone)]
pub struct Config {
    pub udp_bind: String,
    pub udp_peer: String,    // 仅日志展示用（接收端不主动连）
    pub num_workers: usize,
    pub max_queue_size: usize,

    pub ws_host: String,
    pub ws_port: u16,

    pub debug: bool,
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            // hqserverd 默认绑 192.168.1.* 网段的 UDP 端口，接收 quota.py 推送
            udp_bind: env_or("HQ_UDP_BIND", "0.0.0.0:9001"),
            udp_peer: env_or("QUOTA_UDP_HOST", "192.168.1.20"), // 信息展示用
            num_workers: env_int("HQ_NUM_WORKERS", 4).max(1) as usize,
            max_queue_size: env_int("HQ_MAX_QUEUE_SIZE", 5000).max(64) as usize,

            ws_host: env_or("HQ_WS_HOST", "0.0.0.0"),
            ws_port: env_int("HQ_WS_PORT", 8765) as u16,

            debug: env_bool("HQ_DEBUG", false),
        }
    }
}