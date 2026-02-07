from agent.sheets import read_last_rows

def build_context(spreadsheet_id: str, n: int = 40):
    _, calendar_rows = read_last_rows(spreadsheet_id, "calendar", n)
    _, swipe_rows = read_last_rows(spreadsheet_id, "swipe_file", n)
    _, perf_rows = read_last_rows(spreadsheet_id, "performance", n)
    return calendar_rows, swipe_rows, perf_rows
