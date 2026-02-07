import gspread
import google.auth
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_client():
    creds, _ = google.auth.default(scopes=SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return gspread.authorize(creds)

def append_rows(spreadsheet_id: str, sheet_name: str, rows: list[list]):
    gc = get_client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(sheet_name)
    ws.append_rows(rows, value_input_option="USER_ENTERED")

def read_last_rows(spreadsheet_id: str, sheet_name: str, n: int = 50):
    gc = get_client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(sheet_name)
    values = ws.get_all_values()
    if not values:
        return [], []
    header = values[0]
    rows = values[1:]
    return header, rows[-n:]
