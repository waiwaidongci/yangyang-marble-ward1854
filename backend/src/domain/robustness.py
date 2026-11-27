"""Tone-deviation grid and robust handover kits across the whole deviation interval.

色卡磨花后，同一来源批次（``lot_id``）的待分拣料共用一个未知明度偏差，台账只
给出全批统一的上下限。标尺（train/holdout 的均值与标准差）仍按历史读数冻结，
仅在每个偏差场景里重算入树单件的明度标准化坐标、Ward 树和切树比选。

每个偏差场景都按原规则（可交接件数最多，同分取较小簇数）选出推荐切法，该切法
下满足套件件数和簇根 Ward 距离门槛的组才是该场景可交接的套件。一个名义套件
只有在偏差网格的每个场景里都以逐件相同的成员出现在推荐切法中、并且始终达标，
才允许交接；否则撤下并记录第一个使其失败的偏差场景作为作证。

网格取各批 ``{下限, 区间锚点, 上限}`` 的笛卡尔积：锚点优先取 0（0 不在区间内时
取上下限中点），保证名义读数与上下限端点都被覆盖。
"""

from itertools import product

from .cuts import compare_cuts
from .scaling import fit_scales
from .settings import MAX_DEVIATION_SCENARIOS
from .ward import build_tree


def deviation_levels(lower: float, upper: float) -> tuple[float, ...]:
    """Distinct deviation levels sampled for one lot, anchored at the nominal 0."""
    anchor = 0.0 if lower <= 0.0 <= upper else (lower + upper) / 2
    levels = []
    for value in (lower, anchor, upper):
        value = round(value, 6)
        if value not in levels:
            levels.append(value)
    return tuple(levels)


def deviation_grid(lot_ids: tuple[str, ...], lower: float, upper: float) -> list[dict]:
    """Cartesian product of per-lot deviation levels as ``lot_id -> offset`` maps."""
    levels = deviation_levels(lower, upper)
    anchor = 0.0 if lower <= 0.0 <= upper else round((lower + upper) / 2, 6)
    count = len(levels) ** len(lot_ids)
    if count > MAX_DEVIATION_SCENARIOS:
        raise ValueError(
            f'明度偏差场景共 {count} 个，超过上限 {MAX_DEVIATION_SCENARIOS}。'
            '请缩小区间、减少待分拣批次或拆分台账后再提交。')
    grid = []
    for number, picked in enumerate(product(levels, repeat=len(lot_ids))):
        offsets = dict(zip(lot_ids, picked))
        grid.append({'scenario': number, 'offsets': offsets,
                     'is_anchor': all(value == anchor for value in picked)})
    return grid


def _eligible_lots(eligible: list[dict]) -> tuple[str, ...]:
    return tuple(sorted({row['lot_id'] for row in eligible}))


def _scenario_pipeline(eligible: list[dict], offsets: dict[str, float], scales, options) -> dict:
    """Rebuild the Ward tree and cut comparison under one deviation scenario."""
    coordinates = {}
    for row in eligible:
        offset = offsets.get(row['lot_id'], 0.0)
        moved = dict(row)
        moved['tone_lstar'] = row['tone_lstar'] + offset
        coordinates[row['id']] = tuple(scale.apply(moved) for scale in scales)
    tree = build_tree(coordinates)
    cuts, members, recommended = compare_cuts(tree, options, eligible)
    groups = {}
    for row in members:
        group = groups.setdefault(row['group_id'], {
            'clusters': row['clusters'], 'node': row['node'], 'members': [],
            'kit_status': row['kit_status'], 'reason': row['reason'],
            'group_pieces': row['group_pieces'], 'group_ward_distance': row['group_ward_distance']})
        group['members'].append(row['id'])
    for group in groups.values():
        group['members'] = tuple(sorted(group['members']))
    # group_id 内含切树簇数，天然区分不同切法；成员相同的组会在多套切法里重复出现。
    recommended_ready = {group_id: group for group_id, group in groups.items()
                         if recommended is not None and group['clusters'] == recommended
                         and group['kit_status'] == 'ready'}
    by_members = {}
    for group_id, group in groups.items():
        by_members.setdefault(group['members'], []).append((group_id, group))
    return {'tree': tree, 'cuts': cuts, 'members': members, 'recommended': recommended,
            'groups': groups, 'by_members': by_members, 'recommended_ready': recommended_ready}


def analyze_robustness(eligible: list[dict], options: dict, tone_weight: float,
                       reference: list[dict]) -> dict:
    """Certify nominal kits whose members stay identical and qualified in every scenario."""
    lower, upper = options['tone_deviation_min'], options['tone_deviation_max']
    lot_ids = _eligible_lots(eligible)
    grid = deviation_grid(lot_ids, lower, upper)
    scales = fit_scales(reference, tone_weight)
    pipelines = []
    scenarios = []
    for cell in grid:
        outcome = _scenario_pipeline(eligible, cell['offsets'], scales, options)
        pipelines.append((cell, outcome))
        scenarios.append({
            'scenario': cell['scenario'],
            'is_anchor': cell['is_anchor'],
            'lot_offsets': ';'.join(f'{lot}={round(cell["offsets"][lot], 6):g}' for lot in lot_ids),
            'recommended_clusters': outcome['recommended'],
            'ready_groups': len(outcome['recommended_ready']),
            'ready_pieces': sum(group['group_pieces'] for group in outcome['recommended_ready'].values()),
        })

    nominal_index = next(index for index, cell in enumerate(grid) if cell['is_anchor'])
    nominal_cell, nominal = pipelines[nominal_index]
    # 套件身份固定为名义场景推荐切法里的成员集合，避免簇号随场景变化导致误判。
    robust_rows = []
    removed_rows = []
    nominal_kits = list(nominal['recommended_ready'].values())
    for order, base in enumerate(nominal_kits, 1):
        witness = None
        max_distance = base['group_ward_distance']
        for cell, outcome in pipelines:
            if cell['scenario'] == nominal_cell['scenario']:
                continue
            matches = outcome['by_members'].get(base['members'], [])
            if not matches:
                witness = {'scenario': cell['scenario'], 'offsets': cell['offsets'],
                           'reason': 'members_changed'}
                break
            # 同成员组可能在多套切法里出现，取该场景推荐切法中的那一个。
            same_members = next((group for group_id, group in matches
                                 if group['clusters'] == outcome['recommended']), None)
            if same_members is None:
                witness = {'scenario': cell['scenario'], 'offsets': cell['offsets'],
                           'reason': 'not_in_recommended_cut'}
                break
            max_distance = max(max_distance, same_members['group_ward_distance'])
            if same_members['kit_status'] != 'ready':
                witness = {'scenario': cell['scenario'], 'offsets': cell['offsets'],
                           'reason': same_members['reason'] or 'not_ready'}
                break
        common = {
            'robust_kit_id': f'R{order:02d}',
            'nominal_group_id': next(group_id for group_id, group in nominal['groups'].items()
                                     if group['members'] == base['members']
                                     and group['clusters'] == nominal['recommended']),
            'clusters': base['clusters'], 'node': base['node'],
            'kit_pieces': base['group_pieces'], 'members': base['members'],
            'max_ward_distance': max_distance,
        }
        if witness is None:
            robust_rows.append({**common, 'kit_status': 'ready',
                                'tone_deviation_min': lower, 'tone_deviation_max': upper})
        else:
            removed_rows.append({**common, 'kit_status': 'hold', 'witness_scenario': witness['scenario'],
                                 'witness_offsets': ';'.join(
                                     f'{lot}={round(witness["offsets"][lot], 6):g}' for lot in lot_ids),
                                 'reason': witness['reason']})

    return {
        'lot_ids': lot_ids,
        'scenario_count': len(grid),
        'scenarios': scenarios,
        'robust_kits': robust_rows,
        'removed_kits': removed_rows,
        'nominal_members': nominal['members'],
        'nominal_tree': nominal['tree'],
        'nominal_cuts': nominal['cuts'],
        'nominal_recommended': nominal['recommended'],
    }
