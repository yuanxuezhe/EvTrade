//! 跨模块数据类型：WS 推送给前端的 payload
//! 与旧 hqserver.py 完全等价（前端无感知）：
//!   {"type":"quote","channel":"quote_update","data":{stock_code,last_price,fields,body}}
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct QuoteFields {
    pub stock_code: String,
    pub last_price: Option<f64>,
    pub fields: Vec<String>,
    pub body: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct QuotePayload {
    #[serde(rename = "type")]
    pub kind: &'static str,
    pub channel: &'static str,
    pub data: QuoteFields,
}

impl QuotePayload {
    pub fn new(stock_code: String, fields: Vec<String>, body: String) -> Self {
        // 字段位置定义见 quota.py:format_quote
        //   0:stock_code 1:stime 2:last 4:open 5:high 6:low 7:lastClose ...
        let last_price = fields
            .get(2)
            .and_then(|s| s.parse::<f64>().ok());

        Self {
            kind: "quote",
            channel: "quote_update",
            data: QuoteFields {
                stock_code,
                last_price,
                fields,
                body,
            },
        }
    }
}