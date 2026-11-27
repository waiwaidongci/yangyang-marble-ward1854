"""Backend entry points for dataset import, deterministic seed and worker analysis."""

from .fixtures import demo_rows
from .records import normalize_rows, size_screen
from .reports import build_reports, tone_tables
from .robustness import analyze_robustness
from .scaling import fit_scales, scale_diagnostics
from .settings import SPEC, SPLITS, parse_settings

__all__ = ['SPEC', 'demo_rows', 'normalize_rows', 'analyze']


def analyze(rows: list[dict], settings: dict) -> dict:
    options = parse_settings(settings)
    cohorts = {split: [] for split in SPLITS}
    for row in normalize_rows(rows):
        cohorts[row['split']].append(row)
    reference = cohorts['train']
    holdout = cohorts['holdout']
    scales = fit_scales(reference, options['tone_weight'])
    diagnostic = scale_diagnostics(scales, len(reference), holdout)
    eligible, aside = size_screen(cohorts['pending'], options)

    warnings = []
    if not holdout:
        warnings.append('台账没有留出标尺，无法检查标尺批之间的均值偏移。')
    if not eligible:
        warnings.append('全部待分拣单件低于尺寸门槛，本次无可切树数据。')
    elif len(eligible) < options['max_clusters']:
        warnings.append(f'符合尺寸的边角料仅 {len(eligible)} 件，候选簇数上限按实际件数收缩。')

    tree, cuts, members, recommended, robust = None, [], [], None, None
    if eligible:
        # 名义读数（锚点偏差）与区间内其余场景共用同一套建树、切树和比选规则。
        robust = analyze_robustness(eligible, options, options['tone_weight'], reference)
        tree = robust['nominal_tree']
        cuts = robust['nominal_cuts']
        members = robust['nominal_members']
        recommended = robust['nominal_recommended']
        if cuts and recommended is None:
            warnings.append('没有候选同时满足套件件数与合并距离门槛，所有入树单件暂缓交接。')
        if options['tone_deviation_min'] != options['tone_deviation_max']:
            if robust['robust_kits']:
                warnings.append(
                    f"明度偏差区间 [{options['tone_deviation_min']}, {options['tone_deviation_max']}] 内，"
                    f"{len(robust['robust_kits'])} 套套件在各场景推荐切法中成员始终相同且达标，可交接；"
                    f"{len(robust['removed_kits'])} 套名义套件被撤下，详见作证表。")
            else:
                warnings.append('明度偏差区间内没有成员始终相同且达标的套件，本次不交接任何套件。')

    tables = build_reports(tree, cuts, members, aside, diagnostic)
    if robust is not None:
        tables.extend(tone_tables(robust, eligible, options))

    chosen = next((cut for cut in cuts if cut.get('recommended')), None)
    kits = chosen['kits_ready'] if chosen else 0
    packed = chosen['pieces_ready'] if chosen else 0
    cut_note = f'建议切成 {recommended} 簇，可交接 {kits} 套共 {packed} 件。' if chosen else '本次暂无可交接套件。'
    metrics = {'历史标尺件数': len(reference), '留出标尺件数': len(holdout), '入树件数': len(eligible),
               '尺寸不足件数': len(aside), '切树候选数': len(cuts), '建议切树簇数': recommended,
               '建议交接套数': kits, '建议交接件数': packed}
    if robust is not None:
        metrics.update({'明度偏差场景数': robust['scenario_count'],
                        '全区间可交接套数': len(robust['robust_kits']),
                        '全区间可交接件数': sum(kit['kit_pieces'] for kit in robust['robust_kits']),
                        '撤下套件数': len(robust['removed_kits'])})
    return {
        'summary': (f'用 {len(reference)} 件历史料冻结长边、短边和明度缩放。'
                    f'{len(eligible)} 件待分拣料进入 Ward 树，{len(aside)} 件尺寸不足搁置。' + cut_note),
        'metrics': metrics,
        'tables': tables,
        'warnings': warnings,
        'tone_interval': (None if robust is None else {
            'tone_deviation_min': options['tone_deviation_min'],
            'tone_deviation_max': options['tone_deviation_max'],
            'scenario_count': robust['scenario_count'],
            'robust_kits': len(robust['robust_kits']),
            'removed_kits': len(robust['removed_kits'])}),
    }
