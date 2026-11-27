from fastapi.responses import Response

from src.services import reinspections
from src.services.reviews import review_info
from src.services.runs import export_table, get_run, run_info
from src.utils.csv_files import write_rows


def report_detail(session, run_id, actor):
    run, review = get_run(session, run_id, actor)
    versions = [reinspections.serialize(entry)
                for entry in reinspections.list_versions(session, run_id)]
    effective_lower, effective_upper = reinspections.current_interval(session, run)
    return {**run_info(run, review), 'result': run.result, 'error': run.error,
            'review': review_info(review) if review else None,
            'effective_tone_interval': {'tone_deviation_min': effective_lower,
                                        'tone_deviation_max': effective_upper},
            'reinspections': versions}


def report_csv(session, run_id, key, actor):
    table = export_table(session, run_id, key, actor)
    return Response(write_rows(table['columns'], table['rows']), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="run-{run_id}-{table["key"]}.csv"'})
