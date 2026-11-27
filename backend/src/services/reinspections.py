"""Late tone-card reinspections: append-only widening of the deviation interval.

补录（复检）与下载可能并发。复检在运行行锁内把新区间快照写入并提交，导出在同一
把行锁内读取已提交的最新快照，因此一张交接单的全部内容都取自同一个已生效区间，
不会出现半新半旧的混合结果。原运行结果和复核签核永不改写，历史区间版本保留可查。
"""

from fastapi import HTTPException
from sqlalchemy import select

from src.constants.workflow import Decision, RunStatus
from src.domain.project import analyze
from src.domain.reports import tone_tables
from src.models.dataset import Dataset
from src.models.reinspection import Reinspection
from src.models.review import Review
from src.models.run import Run
from src.services.audit import record
from src.utils.time import utc_stamp

TONE_TABLE_KEYS = ('tone_intervals', 'robust_kit_members', 'removed_kit_witnesses', 'deviation_scenarios')


def _locked_run(session, run_id) -> Run:
    run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run is None:
        raise LookupError('找不到运行')
    return run


def current_interval(session, run: Run) -> tuple[float, float]:
    """Effective deviation interval: latest reinspection, else the run's own settings."""
    latest = session.scalar(select(Reinspection).where(Reinspection.run_id == run.id)
                            .order_by(Reinspection.version.desc()).limit(1))
    if latest is not None:
        return latest.tone_deviation_min, latest.tone_deviation_max
    return run.settings.get('tone_deviation_min', 0), run.settings.get('tone_deviation_max', 0)


def list_versions(session, run_id: int) -> list[Reinspection]:
    return list(session.scalars(select(Reinspection).where(Reinspection.run_id == run_id)
                                .order_by(Reinspection.version)))


def _ensure_widening(old_lower, old_upper, new_lower, new_upper):
    if new_lower > new_upper:
        raise ValueError('明度共用偏差下限须小于或等于上限。')
    if new_lower > old_lower or new_upper < old_upper:
        raise HTTPException(422, '复检只允许放宽区间：新下限不得高于旧下限，新上限不得低于旧上限。')
    if new_lower == old_lower and new_upper == old_upper:
        raise HTTPException(409, '新区间与当前生效区间相同，无需补录复检。')


def add_reinspection(session, run_id, payload, actor) -> dict:
    run = _locked_run(session, run_id)
    if run.status != RunStatus.COMPLETED:
        raise HTTPException(409, '仅计算成功完成的运行可补录复检。')
    review = session.get(Review, run_id)
    if review is None or review.decision != Decision.APPROVED:
        raise HTTPException(409, '运行签核通过后，晚到的色卡复检才可放宽区间。')
    old_lower, old_upper = current_interval(session, run)
    _ensure_widening(old_lower, old_upper, payload.tone_deviation_min, payload.tone_deviation_max)

    settings = {**run.settings,
                'tone_deviation_min': payload.tone_deviation_min,
                'tone_deviation_max': payload.tone_deviation_max}
    result = analyze(run_dataset_rows(session, run), settings)
    interval = result['tone_interval']
    tone = {table['key']: table for table in result['tables'] if table['key'] in TONE_TABLE_KEYS}
    robust_summary = next(table for table in result['tables'] if table['key'] == 'robust_kit_members')
    removed_summary = next(table for table in result['tables'] if table['key'] == 'removed_kit_witnesses')
    robust_kits = _kit_index(robust_summary['rows'])
    removed_kits = _kit_index(removed_summary['rows'])

    previous = session.scalar(select(Reinspection).where(Reinspection.run_id == run_id)
                              .order_by(Reinspection.version.desc()).limit(1))
    version = 1 if previous is None else previous.version + 1
    entry = Reinspection(
        run_id=run_id, version=version,
        tone_deviation_min=payload.tone_deviation_min, tone_deviation_max=payload.tone_deviation_max,
        scenario_count=interval['scenario_count'], robust_kits=robust_kits, removed_kits=removed_kits,
        tables={key: tone[key] for key in TONE_TABLE_KEYS}, note=payload.note,
        created_by=actor.id, created_at=utc_stamp())
    session.add(entry)
    session.flush()
    record(session, 'reinspection.recorded', entry.id, actor.id)
    session.commit()
    return serialize(entry)


def run_dataset_rows(session, run: Run) -> list[dict]:
    dataset = session.get(Dataset, run.dataset_id)
    if dataset is None:
        raise LookupError('找不到来源台账')
    return dataset.rows


def _kit_index(rows: list[dict]) -> list[dict]:
    kits = {}
    for row in rows:
        kits.setdefault(row['robust_kit_id'], {**row, 'members': []})
        kits[row['robust_kit_id']]['members'].append(row['id'])
    return [kits[key] for key in sorted(kits)]


def serialize(entry: Reinspection) -> dict:
    return {'id': entry.id, 'run_id': entry.run_id, 'version': entry.version,
            'tone_deviation_min': entry.tone_deviation_min,
            'tone_deviation_max': entry.tone_deviation_max,
            'scenario_count': entry.scenario_count,
            'robust_kit_count': len(entry.robust_kits),
            'removed_kit_count': len(entry.removed_kits),
            'note': entry.note, 'created_at': entry.created_at}


def effective_snapshot(session, run_id: int) -> tuple[Run, Reinspection | None, dict[str, dict]]:
    """Lock the run and return the tone tables of the currently effective interval.

    与 :func:`add_reinspection` 共用运行行锁：补录提交前到达的导出读取旧快照，提交
    后到达的读取新快照，整份导出始终对应单一已生效区间。
    """
    run = _locked_run(session, run_id)
    latest = session.scalar(select(Reinspection).where(Reinspection.run_id == run_id)
                            .order_by(Reinspection.version.desc()).limit(1))
    if latest is not None:
        return run, latest, latest.tables
    tables = {table['key']: table for table in run.result['tables'] if table['key'] in TONE_TABLE_KEYS}
    return run, None, tables
