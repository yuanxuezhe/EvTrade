#!/usr/bin/env python3
"""
scripts/init_strategy_exec_env.py — strategy_exec 初始化脚本

功能:
1. 生成 STRATEGY_EXEC_API_TOKEN (两服务通信密钥)
2. 生成 RabbitMQ exchange/queue 声明 (幂等)
3. 输出推荐的环境变量配置

用法:
    # 生成配置
    python scripts/init_strategy_exec_env.py

    # 跳过 RabbitMQ 声明 (本机无 broker / 测试环境)
    python scripts/init_strategy_exec_env.py --skip-rabbitmq

前提:
    - RabbitMQ 已运行 (或 --skip-rabbitmq 跳过)
    - strategy_exec 的 .env 已准备好

注:
    signal_consumer 调 /api/orders/place 的鉴权已改为 EVTRADE_SERVICE_TOKEN /
    EVTRADE_ADMIN_TOKEN 直配 (2026-08-25 cleanup-ai-remove 删 /api/auth/grant),
    本脚本不再请求 grant token, 请在 server/.env 直接配 EVTRADE_SERVICE_TOKEN。
"""

import argparse
import os
import secrets
import sys
from pathlib import Path


def generate_token(length: int = 32) -> str:
    """生成随机 hex token"""
    return secrets.token_hex(length)


def check_rabbitmq(rabbitmq_url: str) -> bool:
    """检查 RabbitMQ 连通性"""
    try:
        import pika
        params = pika.URLParameters(rabbitmq_url)
        conn = pika.BlockingConnection(params)
        conn.close()
        return True
    except Exception as e:
        print(f"  [!] RabbitMQ 连接失败: {e}")
        return False


def declare_exchange_and_queue(rabbitmq_url: str, exchange: str, queue: str) -> bool:
    """声明 RabbitMQ exchange + queue (幂等)"""
    try:
        import pika
        params = pika.URLParameters(rabbitmq_url)
        conn = pika.BlockingConnection(params)
        ch = conn.channel()

        # declare exchange
        ch.exchange_declare(
            exchange=exchange,
            exchange_type="topic",
            durable=True,
        )
        print(f"  [OK] exchange declared: {exchange}")

        # declare queue
        ch.queue_declare(queue=queue, durable=True)
        print(f"  [OK] queue declared: {queue}")

        # bind queue to exchange
        ch.queue_bind(exchange=exchange, queue=queue, routing_key="#")
        print(f"  [OK] queue bound to exchange (routing_key=#)")

        conn.close()
        return True
    except Exception as e:
        print(f"  [!] RabbitMQ 声明失败: {e}")
        return False


def update_strategy_exec_env(env_file: Path, api_token: str) -> None:
    """更新 strategy_exec/.env 文件"""
    lines = []
    updated = False
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    new_lines = []
    for line in lines:
        if line.startswith("STRATEGY_EXEC_API_TOKEN="):
            new_lines.append(f"STRATEGY_EXEC_API_TOKEN={api_token}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"STRATEGY_EXEC_API_TOKEN={api_token}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"  [OK] strategy_exec/.env 已更新: STRATEGY_EXEC_API_TOKEN={api_token[:8]}...")


def main() -> None:
    parser = argparse.ArgumentParser(description="strategy_exec 环境初始化")
    parser.add_argument(
        "--rabbitmq-url",
        default=os.environ.get("RABBITMQ_URL", ""),
        help="RabbitMQ URL (默认从 RABBITMQ_URL 读)",
    )
    parser.add_argument(
        "--evtrade-db-url",
        default=os.environ.get("EVTRADE_DB_URL", ""),
        help="EvTrade MySQL URL (strategy_exec 用)",
    )
    parser.add_argument(
        "--skip-rabbitmq",
        action="store_true",
        help="跳过 RabbitMQ exchange/queue 声明",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("strategy_exec 初始化脚本")
    print("=" * 60)

    # ── 1. 生成 API token ──────────────────────────────
    print("\n[1] 生成 STRATEGY_EXEC_API_TOKEN ...")
    api_token = generate_token(32)
    print(f"  [OK] {api_token[:8]}...{api_token[-4:]} (全长 {len(api_token)})")

    # ── 2. 更新 strategy_exec/.env ────────────────────
    env_file = Path(__file__).parent.parent / "strategy_exec" / ".env"
    if env_file.exists():
        update_strategy_exec_env(env_file, api_token)
    else:
        print(f"  [!] strategy_exec/.env 不存在，跳过自动更新")
        print(f"      请手动添加到 .env: STRATEGY_EXEC_API_TOKEN={api_token}")

    # ── 3. RabbitMQ ────────────────────────────────────
    if not args.skip_rabbitmq:
        print("\n[2] 声明 RabbitMQ exchange/queue ...")
        rabbitmq_url = args.rabbitmq_url
        if not rabbitmq_url:
            print("  [!] RABBITMQ_URL 未设置，使用默认值")
            rabbitmq_url = "amqp://guest:guest@localhost:5672/"

        if check_rabbitmq(rabbitmq_url):
            declare_exchange_and_queue(
                rabbitmq_url,
                exchange="strategy.exchange",
                queue="EvTrade.StrategySignal",
            )
    else:
        print("\n[2] 跳过 RabbitMQ 声明 (--skip-rabbitmq)")

    # ── 4. 输出汇总 ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("推荐环境变量配置")
    print("=" * 60)

    # EvTrade 侧
    print("\n## EvTrade (server/.env 或 docker-compose.yml) ##")
    print("# EVTRADE_SERVICE_TOKEN=  # signal_consumer 调 /api/orders/place 用, 直配 (cleanup-ai-remove 后无 /grant)")
    print(f"STRATEGY_EXEC_API_URL=http://127.0.0.1:8001")
    print(f"STRATEGY_EXEC_API_TOKEN={api_token}")
    print(f"STRATEGY_EXEC_API_TOKEN两边必须一致!")

    # strategy_exec 侧
    print("\n## strategy_exec (strategy_exec/.env) ##")
    print(f"STRATEGY_EXEC_API_TOKEN={api_token}   # 与 EvTrade 侧一致")
    if args.evtrade_db_url:
        print(f"EVTRADE_DB_URL={args.evtrade_db_url}")
    else:
        print("# EVTRADE_DB_URL=  # MySQL 连接串 (strategy_exec 直连 EvTrade DB)")
    if args.rabbitmq_url:
        print(f"EVTRADE_RABBITMQ_URL={args.rabbitmq_url}")
    else:
        print("# EVTRADE_RABBITMQ_URL=  # RabbitMQ 连接串")

    print("\n## RabbitMQ (两端相同) ##")
    print("strategy.exchange (topic, durable=True)")
    print("EvTrade.StrategySignal (durable=True, bound with routing_key=#)")
    print("strategy_exec 推送 signal → EvTrade 订阅消费")

    print("\n[done]")


if __name__ == "__main__":
    main()
