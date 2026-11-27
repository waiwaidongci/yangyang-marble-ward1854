"""Labeled, flat result tables shared by JSON and signed CSV exports."""

from .settings import FIELDS
from .ward import Tree

PIECE_FIELDS = {key: label for key, label in FIELDS.items() if key != 'split'}

def table(key: str, title: str, labels: dict[str, str], rows: list[dict]) -> dict:
    return {'key': key, 'title': title, 'columns': list(labels), 'labels': labels,
            'rows': [{field: row[field] for field in labels} for row in rows]}


def merge_rows(tree: Tree) -> list[dict]:
    if tree is None:
        return []
    return [{'step': step, 'node': merge.node, 'left': merge.left, 'right': merge.right,
             'left_first_piece': tree.nodes[merge.left].members[0], 'right_first_piece': tree.nodes[merge.right].members[0],
             'left_pieces': len(tree.nodes[merge.left].members), 'right_pieces': len(tree.nodes[merge.right].members),
             'ward_distance': tree.nodes[merge.node].height, 'delta_sse': merge.delta_sse,
             'node_sse': tree.nodes[merge.node].sse, 'partition_sse': merge.partition_sse,
             'clusters_after_merge': tree.leaves - step}
            for step, merge in enumerate(tree.merges, 1)]


def build_reports(tree: Tree | None, cuts: list[dict], members: list[dict], aside: list[dict], scales: list[dict]) -> list[dict]:
    return [
        table('cut_candidates', '切树套件候选比选', {
            'clusters': '切树簇数', 'kits_ready': '可交接套数', 'pieces_ready': '可交接件数',
            'pieces_held': '暂缓件数', 'within_sse': '切树后总簇内 SSE', 'last_included_distance': '已纳入的最后合并距离',
            'next_merge_distance': '下一次合并距离', 'min_kit_pieces': '每套最少件数',
            'max_ward_distance': '套件距离上限', 'recommended': '建议切法'}, cuts),
        table('kit_members', '各切树候选套件成员', {
            'clusters': '切树簇数', 'group_id': '候选组编号', 'node': '树节点号', **PIECE_FIELDS,
            'group_pieces': '组内件数', 'group_sse': '簇内 SSE', 'group_ward_distance': '簇根合并距离',
            'kit_status': '交接状态', 'reason': '暂缓原因'}, members),
        table('ward_merges', 'Ward 层次与逐次合并代价', {
            'step': '合并步号', 'node': '合并节点号', 'left': '左子节点号', 'right': '右子节点号',
            'left_first_piece': '左簇最先编号', 'right_first_piece': '右簇最先编号', 'left_pieces': '左簇件数',
            'right_pieces': '右簇件数', 'ward_distance': 'Ward 合并距离', 'delta_sse': '此次合并 SSE 增量',
            'node_sse': '新簇 SSE', 'partition_sse': '合并后全台账簇内 SSE',
            'clusters_after_merge': '合并后簇数'}, merge_rows(tree)),
        table('scaling', '历史冻结标尺与留出批漂移', {
            'feature': '字段名', 'reference_count': '历史标尺件数', 'reference_mean': '历史均值',
            'reference_population_sd': '历史总体标准差', 'scale_floor': '有效尺度下限',
            'effective_scale': '有效尺度', 'coordinate_weight': '标准化坐标倍率', 'holdout_count': '留出件数',
            'holdout_mean': '留出均值', 'holdout_shift_sd': '留出均值偏移（有效尺度单位）'}, scales),
        table('set_aside', '尺寸不足单件搁置清单', {
            **PIECE_FIELDS, 'min_long_mm': '最小长边（mm）', 'min_short_mm': '最小短边（mm）', 'reason': '搁置原因'}, aside),
    ]


def tone_tables(robust: dict, eligible: list[dict], options: dict) -> list[dict]:
    """Tables certifying kits that keep identical, qualifying members over the deviation interval."""
    sources = {row['id']: row for row in eligible}
    lower, upper = options['tone_deviation_min'], options['tone_deviation_max']
    interval = {'tone_deviation_min': lower, 'tone_deviation_max': upper,
                'scenario_count': robust['scenario_count'],
                'lot_count': len(robust['lot_ids']),
                'lot_ids': ';'.join(robust['lot_ids'])}
    member_rows = []
    for kit in robust['robust_kits']:
        for piece in kit['members']:
            member_rows.append({**sources[piece], **{
                'robust_kit_id': kit['robust_kit_id'], 'nominal_group_id': kit['nominal_group_id'],
                'clusters': kit['clusters'], 'kit_pieces': kit['kit_pieces'],
                'max_ward_distance': kit['max_ward_distance'], 'kit_status': kit['kit_status'],
                'tone_deviation_min': lower, 'tone_deviation_max': upper}})
    removed_rows = []
    for kit in robust['removed_kits']:
        for piece in kit['members']:
            removed_rows.append({**sources[piece], **{
                'robust_kit_id': kit['robust_kit_id'], 'nominal_group_id': kit['nominal_group_id'],
                'clusters': kit['clusters'], 'kit_pieces': kit['kit_pieces'],
                'max_ward_distance': kit['max_ward_distance'], 'kit_status': kit['kit_status'],
                'witness_scenario': kit['witness_scenario'], 'witness_offsets': kit['witness_offsets'],
                'reason': kit['reason']}})
    return [
        table('tone_intervals', '色卡偏差区间与生效网格', {
            'tone_deviation_min': '明度偏差下限（L*）', 'tone_deviation_max': '明度偏差上限（L*）',
            'scenario_count': '偏差场景数', 'lot_count': '入树批次数', 'lot_ids': '入树批次'}, [interval]),
        table('robust_kit_members', '全偏差区间可交接套件成员', {
            'robust_kit_id': '稳健套件编号', 'nominal_group_id': '名义候选组编号', 'clusters': '名义切树簇数',
            **PIECE_FIELDS, 'kit_pieces': '套件件数', 'max_ward_distance': '区间内最大簇根距离',
            'kit_status': '交接状态', 'tone_deviation_min': '明度偏差下限（L*）',
            'tone_deviation_max': '明度偏差上限（L*）'}, member_rows),
        table('removed_kit_witnesses', '撤下套件与偏差作证', {
            'robust_kit_id': '套件编号', 'nominal_group_id': '名义候选组编号', 'clusters': '名义切树簇数',
            **PIECE_FIELDS, 'kit_pieces': '套件件数', 'max_ward_distance': '区间内最大簇根距离',
            'kit_status': '交接状态', 'witness_scenario': '作证偏差场景号',
            'witness_offsets': '作证场景各批偏差', 'reason': '撤下原因'}, removed_rows),
        table('deviation_scenarios', '逐偏差场景切树结果', {
            'scenario': '偏差场景号', 'is_anchor': '是否名义锚点场景', 'lot_offsets': '各批明度偏差（L*）',
            'recommended_clusters': '原规则建议簇数', 'ready_groups': '可交接组数',
            'ready_pieces': '可交接件数'}, robust['scenarios']),
    ]
