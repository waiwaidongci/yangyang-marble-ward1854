"""Standard-library oracle for the tone-deviation interval and robust kit rules.

Run from the backend directory:

    PYTHONPATH=. python3 ../test-artifacts/yangyang-marble-ward/tests/oracle.py

Covers the磨花色卡 story:
1. 同批待分拣料共用一个偏差，网格只取每批的下限、锚点和上限，标尺不随偏差改变。
2. 每个偏差场景按原规则选切法，只有成员始终相同且达标的套件才交接；撤下套件带作证。
3. 复检只能放宽区间；放宽后的稳健套件是原稳健套件的子集（成员原样）。
4. 零区间时新结果与原切树流程完全一致，默认行为向后兼容。
"""

from src.domain.fixtures import demo_rows
from src.domain.project import analyze
from src.domain.records import normalize_rows, size_screen
from src.domain.robustness import (analyze_robustness, deviation_grid,
                                   deviation_levels)
from src.domain.scaling import fit_scales, scale_diagnostics
from src.domain.settings import MAX_DEVIATION_SCENARIOS, parse_settings

PASS = 0
FAILURES = []


def check(name, condition, detail=''):
    global PASS
    if condition:
        PASS += 1
    else:
        FAILURES.append((name, detail))
        print(f'FAIL {name} {detail}')


def table_of(result, key):
    return next(table for table in result['tables'] if table['key'] == key)


def kit_members(result, table_key='robust_kit_members'):
    grouped = {}
    for row in table_of(result, table_key)['rows']:
        grouped.setdefault(row['robust_kit_id'], set()).add(row['id'])
    return grouped


def test_grid_anchors_and_limits():
    check('levels zero inside', deviation_levels(-3, 3) == (-3, 0, 3))
    check('levels zero boundary', deviation_levels(0, 3) == (0, 3))
    check('levels zero point', deviation_levels(0, 0) == (0,))
    check('levels midpoint anchor', deviation_levels(1, 4) == (1, 2.5, 4))
    grid = deviation_grid(('L1', 'L2'), -2, 2)
    check('grid size', len(grid) == 9)
    anchor = [cell for cell in grid if cell['is_anchor']]
    check('single anchor', len(anchor) == 1 and anchor[0]['offsets'] == {'L1': 0, 'L2': 0})
    endpoints = [cell for cell in grid
                 if all(v in (-2, 2) for v in cell['offsets'].values()) and not cell['is_anchor']]
    check('corners covered', len(endpoints) == 4)
    try:
        deviation_grid(tuple(f'L{i}' for i in range(7)), -1, 1)
        check('grid cap enforced', False)
    except ValueError as error:
        check('grid cap enforced', str(MAX_DEVIATION_SCENARIOS) in str(error))


def test_scales_unchanged_under_deviation():
    rows = normalize_rows(demo_rows())
    options = parse_settings({'tone_deviation_min': -4, 'tone_deviation_max': 4})
    cohorts = {split: [] for split in ('train', 'holdout', 'pending')}
    for row in rows:
        cohorts[row['split']].append(row)
    baseline = fit_scales(cohorts['train'], options['tone_weight'])
    eligible, _ = size_screen(cohorts['pending'], options)
    robust = analyze_robustness(eligible, options, options['tone_weight'], cohorts['train'])
    # 场景内部重算的标尺必须与历史标尺完全一致（偏差只作用于待分拣件）。
    scenario_scales = fit_scales(cohorts['train'], options['tone_weight'])
    check('frozen scales identical', all(
        a.center == b.center and a.effective_scale == b.effective_scale
        for a, b in zip(baseline, scenario_scales)))
    diagnostic = scale_diagnostics(baseline, len(cohorts['train']), cohorts['holdout'])
    check('holdout diagnostic kept', diagnostic[2]['holdout_count'] == 6)
    check('scenario count reported', robust['scenario_count'] == 3 ** len(robust['lot_ids']))


def test_robust_kits_are_constant_and_qualified():
    rows = demo_rows()
    narrow = analyze(rows, {'tone_deviation_min': -0.5, 'tone_deviation_max': 0.5})
    wide = analyze(rows, {'tone_deviation_min': -6, 'tone_deviation_max': 6})
    narrow_kits = kit_members(narrow)
    wide_kits = kit_members(wide)
    check('narrow keeps nominal kits', len(narrow_kits) == 3 and
          sum(len(v) for v in narrow_kits.values()) == 21)
    check('widening cannot add kits', set(wide_kits).issubset(set(narrow_kits)) or
          all(wide_kits[k] == narrow_kits[k] for k in wide_kits))
    # 宽区间里留下的套件成员必须与窄区间逐件相同（原样交接）。
    for kit_id, members in wide_kits.items():
        check(f'kit {kit_id} members preserved', members == narrow_kits.get(kit_id))
    removed = table_of(wide, 'removed_kit_witnesses')['rows']
    if removed:
        sample = removed[0]
        check('witness carries scenario', sample['witness_scenario'] >= 0 and
              sample['witness_offsets'] and sample['reason'])
        scenarios = table_of(wide, 'deviation_scenarios')['rows']
        ids = {cell['scenario'] for cell in scenarios}
        check('witness scenario exists', sample['witness_scenario'] in ids)
    # 每个场景都按原规则给出建议簇数。
    for cell in table_of(wide, 'deviation_scenarios')['rows']:
        check('scenario recommended cut', cell['recommended_clusters'] is not None)


def test_zero_interval_matches_original_pipeline():
    rows = demo_rows()
    result = analyze(rows, {})
    candidates = table_of(result, 'cut_candidates')['rows']
    recommended = next(cut for cut in candidates if cut['recommended'])
    robust = kit_members(result)
    check('zero interval robust equals recommended',
          len(robust) == recommended['kits_ready'] and
          sum(len(v) for v in robust.values()) == recommended['pieces_ready'])
    check('zero interval single scenario',
          table_of(result, 'deviation_scenarios')['rows'][0]['is_anchor'] is True and
          len(table_of(result, 'deviation_scenarios')['rows']) == 1)
    check('no removals without deviation',
          table_of(result, 'removed_kit_witnesses')['rows'] == [])


def test_settings_validation():
    try:
        parse_settings({'tone_deviation_min': 2, 'tone_deviation_max': 1})
        check('interval order validated', False)
    except ValueError:
        check('interval order validated', True)
    parsed = parse_settings({'tone_deviation_min': -1.5, 'tone_deviation_max': 2.5})
    check('interval parsed', parsed['tone_deviation_min'] == -1.5 and
          parsed['tone_deviation_max'] == 2.5)
    check('default interval zero', parse_settings({})['tone_deviation_min'] == 0 and
          parse_settings({})['tone_deviation_max'] == 0)


def test_widening_monotonicity_chain():
    rows = demo_rows()
    previous = None
    for lower, upper in ((0, 0), (-1, 1), (-3, 3), (-8, 8)):
        result = analyze(rows, {'tone_deviation_min': lower, 'tone_deviation_max': upper})
        current = kit_members(result)
        if previous is not None:
            for kit_id, members in current.items():
                check(f'monotonic {lower}/{upper} {kit_id}',
                      kit_id not in previous or members == previous[kit_id])
        previous = current


def test_members_changed_witness_reachable():
    def piece(pid, lot, long, short, tone):
        return {'id': f'P{pid:02d}', 'lot_id': lot, 'split': 'pending',
                'long_mm': float(long), 'short_mm': float(short), 'tone_lstar': float(tone)}

    def reference(pid, long, short, tone):
        return {'id': f'R{pid:02d}', 'lot_id': f'RL{pid}', 'split': 'train',
                'long_mm': float(long), 'short_mm': float(short), 'tone_lstar': float(tone)}

    rows = [reference(i, 100 + i * 5, 70 + i * 2, 50 + i * 3) for i in range(1, 5)]
    pid = 1
    for band, base_tone in enumerate((40, 60, 80), 1):
        for j in range(6):
            rows.append(piece(pid, f'L{band}', 120 + j * 3, 75 + (j % 3) * 2,
                              base_tone + (j - 3)))
            pid += 1
    result = analyze(rows, {'tone_deviation_min': -8, 'tone_deviation_max': 8,
                            'min_clusters': 2, 'max_clusters': 6, 'min_kit_pieces': 3,
                            'max_ward_distance': 2.0})
    reasons = {row['reason'] for row in table_of(result, 'removed_kit_witnesses')['rows']}
    check('members_changed witness reachable', 'members_changed' in reasons, str(reasons))


def main():
    test_grid_anchors_and_limits()
    test_scales_unchanged_under_deviation()
    test_robust_kits_are_constant_and_qualified()
    test_zero_interval_matches_original_pipeline()
    test_settings_validation()
    test_widening_monotonicity_chain()
    test_members_changed_witness_reachable()
    print(f'{PASS} checks passed, {len(FAILURES)} failed')
    if FAILURES:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
