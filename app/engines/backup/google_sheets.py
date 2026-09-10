"""Google Sheets v4 writer. Values are always sent as RAW."""

import httpx


class GoogleSheetsError(RuntimeError):
    pass


class GoogleSheetsClient:
    base_url = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, access_token: str) -> None:
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = httpx.request(
                method, url, headers={**self.headers, **kwargs.pop("headers", {})},
                timeout=60, **kwargs,
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleSheetsError("Google Sheets request failed") from exc

    @staticmethod
    def _range(title: str) -> str:
        return "'" + title.replace("'", "''") + "'"

    def replace_tabs(self, spreadsheet_id: str, tabs: dict[str, list[list]]) -> None:
        metadata = self._request(
            "GET", f"{self.base_url}/{spreadsheet_id}",
            params={"fields": "sheets.properties(sheetId,title)"},
        )
        properties = {
            sheet["properties"]["title"]: sheet["properties"]
            for sheet in metadata.get("sheets", [])
        }
        # A Drive-created spreadsheet starts with one empty Sheet1. Reuse it so
        # new BNC workbooks do not keep a meaningless blank tab.
        if tabs and len(properties) == 1 and "Sheet1" in properties and not set(tabs) & set(properties):
            first_title = next(iter(tabs))
            sheet_id = properties["Sheet1"]["sheetId"]
            self._request("POST", f"{self.base_url}/{spreadsheet_id}:batchUpdate", json={
                "requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "title": first_title},
                    "fields": "title",
                }}]
            })
            properties = {first_title: {"sheetId": sheet_id, "title": first_title}}
        missing = [title for title in tabs if title not in properties]
        if missing:
            self._request("POST", f"{self.base_url}/{spreadsheet_id}:batchUpdate", json={
                "requests": [{"addSheet": {"properties": {"title": title}}} for title in missing]
            })
            metadata = self._request(
                "GET", f"{self.base_url}/{spreadsheet_id}",
                params={"fields": "sheets.properties(sheetId,title)"},
            )
            properties = {
                sheet["properties"]["title"]: sheet["properties"]
                for sheet in metadata.get("sheets", [])
            }
        for title, rows in tabs.items():
            clean_rows = [["" if cell is None else cell for cell in row] for row in rows]
            escaped = self._range(title)
            self._request("POST", f"{self.base_url}/{spreadsheet_id}/values/{escaped}:clear")
            self._request("PUT", f"{self.base_url}/{spreadsheet_id}/values/{escaped}!A1", params={
                "valueInputOption": "RAW"
            }, json={"majorDimension": "ROWS", "values": clean_rows})
        requests = []
        for title, rows in tabs.items():
            sheet_id = properties[title]["sheetId"]
            column_count = max((len(row) for row in rows), default=1)
            requests.extend([
                {"updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }},
                {"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": column_count},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.06, "green": 0.36, "blue": 0.23},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }},
                {"autoResizeDimensions": {"dimensions": {
                    "sheetId": sheet_id, "dimension": "COLUMNS",
                    "startIndex": 0, "endIndex": column_count,
                }}},
            ])
        if requests:
            self._request("POST", f"{self.base_url}/{spreadsheet_id}:batchUpdate", json={"requests": requests})
