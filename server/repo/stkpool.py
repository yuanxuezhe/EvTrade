"""
server/repo/stkpool.py — 证券池仓库 (add-stkpool-module change)

封装 stkpool + stkpooldetail 两张表的所有 CRUD 业务流。
走 TableBase 标准接口 (upsert_one / query_one / query_by / delete_one),
不引入新 SQL, 不引入 ORM 依赖。

业务规则:
- 池名去重 (POOL_NAME_DUPLICATE 兜底 + UK 兜底)
- add_detail 前先验池存在 (PoolNotFound)
- 明细表 share-id 模式: id 字段由应用层写入 (= stkpool.id)
- 删池走 MySQL ON DELETE CASCADE, 不显式清理明细

模块规范: openspec/changes/active/add-stkpool-module
  - proposal.md
  - design.md
  - specs/server-architecture/spec.md
"""
from typing import List, Optional

from server.tables.stkpool import Stkpool
from server.tables.stkpooldetail import StkpoolDetail


# ================================================================
# 业务异常 (API 层转 HTTPException)
# ================================================================

class PoolNotFound(Exception):
    """池不存在"""
    def __init__(self, pool_id: int):
        super().__init__(f"POOL_NOT_FOUND: id={pool_id}")
        self.pool_id = pool_id


class PoolNameDuplicate(Exception):
    """池名重复"""
    def __init__(self, name: str):
        super().__init__(f"POOL_NAME_DUPLICATE: '{name}'")
        self.name = name


class DetailNotFound(Exception):
    """明细不存在"""
    def __init__(self, pool_id: int, stock_code: str):
        super().__init__(f"DETAIL_NOT_FOUND: id={pool_id}, stock_code='{stock_code}'")
        self.pool_id = pool_id
        self.stock_code = stock_code


# ================================================================
# 仓库 (CRUD 业务流)
# ================================================================

class StkpoolRepo:
    """证券池仓库: 封装 stkpool + stkpooldetail 两表 CRUD"""

    # ---- 主表 ----

    @staticmethod
    def list_pools() -> List:
        """全量主表, 按 id ASC"""
        return Stkpool.query_all('asc')

    @staticmethod
    def get_pool(pool_id: int):
        """按 id 查单池 → Row | None"""
        return Stkpool.query_one(id=pool_id)

    @staticmethod
    def create_pool(name: str, remark: str = ''):
        """创建池 (name 唯一).

        流程:
            1. query_by('name', name) 查重
            2. 重复 → 抛 PoolNameDuplicate
            3. add_one({'name': name, 'remark': remark})  -- 让 AUTO_INCREMENT 接管 PK
            4. add_one 自动 SELECT * 回填完整 Row

        Returns:
            Row (含 id + created_at)
        """
        existing = Stkpool.query_by('name', name)
        if existing:
            raise PoolNameDuplicate(name)

        # add_one 模式下 PK (AUTO_INCREMENT) 自动跳过, DB 自增
        return Stkpool.add_one({'name': name, 'remark': remark})

    @staticmethod
    def update_pool(pool_id: int, name: Optional[str] = None, remark: Optional[str] = None):
        """改池名/备注 (partial update).

        Raises:
            PoolNotFound: 池不存在
            PoolNameDuplicate: 新名称与其它池冲突
        """
        existing = Stkpool.query_one(id=pool_id)
        if existing is None:
            raise PoolNotFound(pool_id)

        update_data = {}
        if name is not None:
            # 改名前查重 (除自己以外)
            dup = Stkpool.query_by('name', name)
            if dup and any(r.id != pool_id for r in dup):
                raise PoolNameDuplicate(name)
            update_data['name'] = name
        if remark is not None:
            update_data['remark'] = remark

        if not update_data:
            return existing  # noop

        Stkpool.update_one(update_data, id=pool_id)
        return Stkpool.query_one(id=pool_id)

    @staticmethod
    def delete_pool(pool_id: int) -> bool:
        """删池 (MySQL CASCADE 自动清明细).

        Returns:
            True 删除成功, False 池不存在
        """
        return Stkpool.delete_one(id=pool_id)

    # ---- 明细 ----

    @staticmethod
    def list_detail(pool_id: int) -> List:
        """查池 X 所有明细, 按 stock_code ASC.

        Raises:
            PoolNotFound: 池不存在
        """
        if Stkpool.query_one(id=pool_id) is None:
            raise PoolNotFound(pool_id)
        return StkpoolDetail.query_by('id', pool_id, order='asc')

    @staticmethod
    def add_detail(pool_id: int, stock_code: str):
        """加明细 (单条, 兼容旧调用).

        Raises:
            PoolNotFound: 池不存在
        """
        added, skipped = StkpoolRepo.add_detail_batch(pool_id, [stock_code])
        if added > 0:
            return StkpoolDetail.query_one(id=pool_id, stock_code=stock_code)
        # skipped: 已存在, 仍返 Row
        return StkpoolDetail.query_one(id=pool_id, stock_code=stock_code)

    @staticmethod
    def add_detail_batch(pool_id: int, stock_codes: list) -> tuple:
        """批量加明细 (idempotent, 单事务).

        Args:
            pool_id: 主表 id
            stock_codes: stock_code 列表 (调用方需保证已去重 + 校验格式)

        Returns:
            (added: int, skipped: int)

        Raises:
            PoolNotFound: 池不存在
        """
        if Stkpool.query_one(id=pool_id) is None:
            raise PoolNotFound(pool_id)

        if not stock_codes:
            return (0, 0)

        # 去重 (防御性: 调用方可能没去重)
        unique_codes = list(set(stock_codes))

        # 分块单事务 INSERT IGNORE
        # base.py 没有现成 batch_ignore, 用 raw SQL
        # 分块原因: 单条 SQL 受 max_allowed_packet 限制; 单事务过大会卡连接池
        from sqlalchemy import text
        from server.tables.base import get_engine
        CHUNK = 1000
        total_added = 0
        with get_engine().begin() as conn:
            for start in range(0, len(unique_codes), CHUNK):
                chunk = unique_codes[start:start + CHUNK]
                placeholders = ", ".join(f"(:pool_id, :code_{i})" for i in range(len(chunk)))
                params = {'pool_id': pool_id}
                for i, code in enumerate(chunk):
                    params[f'code_{i}'] = code

                sql = text(f"""
                    INSERT IGNORE INTO `stkpooldetail` (id, stock_code)
                    VALUES {placeholders}
                """)
                res = conn.execute(sql, params)
                total_added += res.rowcount

        skipped = len(unique_codes) - total_added
        return (total_added, skipped)

    @staticmethod
    def remove_detail(pool_id: int, stock_code: str) -> bool:
        """删明细 (复合 PK).

        Returns:
            True 删除成功, False 不存在
        """
        return StkpoolDetail.delete_one(id=pool_id, stock_code=stock_code)
