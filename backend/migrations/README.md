# 数据库初始化

`bootstrap.py` 按 SQLAlchemy 模型初始化表结构。后端启动时执行，worker 在后端健康后启动。演示台账与账号使用自然键补齐，后续更新数据时通过导入建立独立快照。

色卡复检功能新增 `tone_reinspections` 表（模型见 `models/reinspection.py`），与既有表一样由 `Base.metadata.create_all` 在启动时自动建立：新环境直接建表，已有环境补齐缺失表，不改动 `analysis_runs`、`reviews` 等历史表。原运行结果与签核保持不可变，区间放宽只向该表追加版本快照。
