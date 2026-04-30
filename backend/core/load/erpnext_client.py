"""Thin Frappe / ERPnext REST client.

Wraps the endpoints we need for live migration: file upload, Data Import,
Chart of Accounts importer, custom doctype config, and read-side queries
for the post-import verification step.

Methods raise `ErpnextError` on non-2xx responses with a normalized
message that includes the Frappe-side traceback when available.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import requests


class ErpnextError(Exception):
    """Frappe returned a non-2xx response. `payload` carries any JSON body."""

    def __init__(self, message: str, status: int = 0, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class ErpnextClient:
    def __init__(self, base_url: str, api_key: str, api_secret: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"token {api_key}:{api_secret}",
            "X-Frappe-CSRF-Token": "",
        })

    # -- low-level ------------------------------------------------------------

    def _request(self, method: str, path: str, **kw) -> Any:
        url = f"{self.base_url}{path}"
        kw.setdefault("timeout", self.timeout)
        try:
            r = self._session.request(method, url, **kw)
        except requests.RequestException as e:
            raise ErpnextError(f"network error calling {method} {path}: {e}") from e
        if r.status_code >= 400:
            payload: Any = None
            try:
                payload = r.json()
            except ValueError:
                payload = r.text
            msg = _extract_error_message(payload) or f"{r.status_code} {r.reason}"
            raise ErpnextError(msg, status=r.status_code, payload=payload)
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def get(self, path: str, **kw) -> Any:
        return self._request("GET", path, **kw)

    def post(self, path: str, json_body: Any = None, **kw) -> Any:
        if json_body is not None:
            kw["json"] = json_body
        return self._request("POST", path, **kw)

    def put(self, path: str, json_body: Any = None, **kw) -> Any:
        if json_body is not None:
            kw["json"] = json_body
        return self._request("PUT", path, **kw)

    # -- file + import --------------------------------------------------------

    def upload_file(self, filename: str, content: bytes, content_type: str = "text/csv") -> str:
        """POST /api/method/upload_file → returns file_url."""
        files = {"file": (filename, content, content_type)}
        resp = self._request("POST", "/api/method/upload_file", files=files)
        return ((resp or {}).get("message") or {}).get("file_url", "")

    def create_data_import(self, doctype: str, file_url: str) -> str:
        """POST /api/resource/Data Import → returns Data Import name."""
        resp = self.post("/api/resource/Data Import", {
            "reference_doctype": doctype,
            "import_type": "Insert New Records",
            "import_file": file_url,
            "mute_emails": 1,
        })
        return ((resp or {}).get("data") or {}).get("name", "")

    def start_data_import(self, name: str) -> Any:
        return self.post(
            "/api/method/frappe.core.doctype.data_import.data_import.form_start_import",
            {"data_import": name},
        )

    def get_data_import_status(self, name: str) -> dict:
        resp = self.get(f"/api/resource/Data Import/{requests.utils.quote(name, safe='')}")
        return (resp or {}).get("data") or {}

    def get_data_import_error_log(self, name: str) -> list[dict]:
        """Fall back to Error Log when import_log is empty."""
        filters = json.dumps([
            ["reference_doctype", "=", "Data Import"],
            ["reference_name", "=", name],
        ])
        fields = json.dumps(["error", "method", "creation"])
        path = (
            "/api/resource/Error Log"
            f"?filters={requests.utils.quote(filters, safe='')}"
            f"&fields={requests.utils.quote(fields, safe='')}"
            "&order_by=creation desc&limit_page_length=5"
        )
        resp = self.get(path)
        return (resp or {}).get("data") or []

    def import_chart_of_accounts(self, file_url: str, company: str) -> Any:
        return self.post(
            "/api/method/erpnext.accounts.doctype.chart_of_accounts_importer."
            "chart_of_accounts_importer.import_coa",
            {"file_name": file_url, "company": company},
        )

    # -- doctype prep ---------------------------------------------------------

    def enable_doctype_import(self, doctype: str) -> None:
        """Idempotent — leaves DocType unchanged if already importable."""
        self.put(
            f"/api/resource/DocType/{requests.utils.quote(doctype, safe='')}",
            {"allow_import": 1},
        )

    def grant_import_perm(self, doctype: str, role: str = "System Manager") -> None:
        """Add a Custom DocPerm with import=1. Idempotent at the row level
        (Frappe creates a fresh row each call; harmless duplication)."""
        self.post("/api/resource/Custom DocPerm", {
            "parent": doctype,
            "parenttype": "DocType",
            "parentfield": "permissions",
            "role": role,
            "permlevel": 0,
            "read": 1, "write": 1, "create": 1, "submit": 1, "import": 1,
        })

    # -- queries --------------------------------------------------------------

    def get_count(self, doctype: str, filters: list | None = None) -> int:
        params = {"doctype": doctype}
        if filters:
            params["filters"] = json.dumps(filters)
        resp = self.get("/api/method/frappe.client.get_count", params=params)
        return int((resp or {}).get("message") or 0)

    def list_companies(self) -> list[str]:
        resp = self.get(
            "/api/resource/Company",
            params={"fields": json.dumps(["name"]), "limit_page_length": 100},
        )
        return [r["name"] for r in (resp or {}).get("data", [])]


# -- helpers ------------------------------------------------------------------

def _extract_error_message(payload: Any) -> str:
    """Pull a human-friendly message from Frappe's nested error shape."""
    if not isinstance(payload, dict):
        return str(payload) if payload else ""
    for key in ("_server_messages", "message", "exception"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            try:
                msgs = json.loads(v)
                if isinstance(msgs, list):
                    return "; ".join(_msg_text(m) for m in msgs)
            except (ValueError, TypeError):
                pass
            return v
    return ""


def _msg_text(m: Any) -> str:
    if isinstance(m, str):
        try:
            obj = json.loads(m)
            if isinstance(obj, dict):
                return obj.get("message") or str(obj)
        except (ValueError, TypeError):
            return m
    if isinstance(m, dict):
        return m.get("message") or str(m)
    return str(m)


def parse_import_log(import_log: str) -> Iterable[dict]:
    """Frappe stores Data Import logs as a JSON-encoded string."""
    if not import_log:
        return []
    try:
        rows = json.loads(import_log)
    except (ValueError, TypeError):
        return []
    return rows if isinstance(rows, list) else []
