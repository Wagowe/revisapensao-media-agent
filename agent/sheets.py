import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_client(service_account_json: str):
    info = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def append_rows(service_account_json: str, spreadsheet_id: str, sheet_name: str, rows: list[list]):
    gc = get_client(service_account_json)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(sheet_name)
    ws.append_rows(rows, value_input_option="USER_ENTERED")

def read_last_rows(service_account_json: str, spreadsheet_id: str, sheet_name: str, n: int = 50):
    gc = get_client(service_account_json)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(sheet_name)
    values = ws.get_all_values()
    if not values:
        return [], []
    header = values[0]
    rows = values[1:]
    return header, rows[-n:]
