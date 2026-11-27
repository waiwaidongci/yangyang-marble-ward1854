from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class Reinspection(Base):
    """晚到色卡复检形成的明度偏差区间版本。

    每次复检只允许把当前生效区间放宽（新下限不高于旧下限、新上限不低于旧上限，
    且至少一端变化）。原始运行结果与签核不可变，区间版本以追加方式保存：导出
    始终读取最新已生效版本中仍能原样交接的套件，历史版本与原签核继续可查。
    """

    __tablename__ = 'tone_reinspections'
    __table_args__ = (UniqueConstraint('run_id', 'version', name='uq_reinspection_run_version'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('analysis_runs.id'), index=True)
    version: Mapped[int] = mapped_column()
    tone_deviation_min: Mapped[float] = mapped_column()
    tone_deviation_max: Mapped[float] = mapped_column()
    scenario_count: Mapped[int] = mapped_column()
    robust_kits: Mapped[list] = mapped_column(JSON)
    removed_kits: Mapped[list] = mapped_column(JSON)
    tables: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey('accounts.id'))
    created_at: Mapped[str] = mapped_column(String(32))
