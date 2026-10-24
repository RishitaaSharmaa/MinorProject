"""NetSuite reader over the SuiteQL REST endpoint, signed with token-based authentication (OAuth 1.0a).

Read-only: it POSTs SELECT statements to `/services/rest/query/v1/suiteql` and pages through the
results. Create an integration record plus an access token for a role with only "View" access to
Vendors, Items, Purchase Orders and Inventory Balance (and the "REST Web Services" and "SuiteAnalytics
Workbook" permissions SuiteQL needs).

Each dataset is one query whose column aliases are the importer's canonical field names. The defaults
below use NetSuite's standard records; accounts differ (custom lead-time fields, subsidiaries, status
codes), so every query can be replaced with `NETSUITE_QUERY_<DATASET>` without changing code. Dates must
come back as text `YYYY-MM-DD` (use TO_CHAR), because SuiteQL otherwise formats them per user preference.
Placeholders: {since} (the lookback date) and {default_lead_time}.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import time
from datetime import date, timedelta
from urllib.parse import quote, unquote, urlsplit

import httpx

from app.config import Settings
from app.sources.base import ErpSource, Row, SourceError

logger = logging.getLogger(__name__)

_PAGE = 1000
_MAX_ROWS = 200_000

DEFAULT_QUERIES = {
    "suppliers": """
        SELECT v.entityid AS supplier_id,
               COALESCE(v.companyname, v.entityid) AS name,
               {default_lead_time} AS quoted_lead_time_days,
               CASE WHEN v.isinactive = 'T' THEN 'strike' ELSE 'clear' END AS strike_status
        FROM vendor v""",
    "items": """
        SELECT i.itemid AS item_id,
               COALESCE(i.displayname, i.itemid) AS name,
               i.cost AS unit_cost,
               i.reorderpoint AS reorder_point_qty,
               v.entityid AS primary_supplier_id
        FROM item i
        LEFT JOIN itemvendor iv ON iv.item = i.id AND iv.preferred = 'T'
        LEFT JOIN vendor v ON v.id = iv.vendor
        WHERE i.isinactive = 'F'""",
    "purchase_orders": """
        SELECT t.tranid || '-' || tl.id AS po_id,
               i.itemid AS item_id,
               v.entityid AS supplier_id,
               ABS(tl.quantity) AS quantity,
               tl.rate AS unit_price,
               TO_CHAR(t.trandate, 'YYYY-MM-DD') AS po_date,
               TO_CHAR(t.duedate, 'YYYY-MM-DD') AS expected_delivery,
               t.memo AS free_text_reason,
               CASE WHEN t.status IN ('H', 'G') THEN 'received'
                    WHEN t.status = 'C' THEN 'cancelled' ELSE 'placed' END AS status
        FROM transaction t
        JOIN transactionline tl ON tl.transaction = t.id
        JOIN item i ON i.id = tl.item
        JOIN vendor v ON v.id = t.entity
        WHERE t.type = 'PurchOrd' AND tl.mainline = 'F' AND tl.item IS NOT NULL
          AND t.trandate >= TO_DATE('{since}', 'YYYY-MM-DD')""",
    "stock_levels": """
        SELECT i.itemid AS item_id,
               TO_CHAR(SYSDATE, 'YYYY-MM-DD') AS date,
               SUM(ib.quantityonhand) AS qty_on_hand
        FROM inventorybalance ib
        JOIN item i ON i.id = ib.item
        GROUP BY i.itemid""",
}


def _pct(value: str) -> str:
    """RFC 3986 percent-encoding as OAuth 1.0a requires."""
    return quote(str(value), safe="~")


def oauth_header(
    method: str, url: str, settings: Settings, *, nonce: str | None = None, timestamp: str | None = None,
) -> str:
    """The `Authorization` header for one request (OAuth 1.0a, HMAC-SHA256, realm = account id)."""
    parts = urlsplit(url)
    params: list[tuple[str, str]] = []
    for pair in filter(None, parts.query.split("&")):
        key, _, value = pair.partition("=")
        params.append((key, value))
    oauth = {
        "oauth_consumer_key": settings.netsuite_consumer_key.get_secret_value(),
        "oauth_token": settings.netsuite_token_id.get_secret_value(),
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_nonce": nonce or secrets.token_hex(10),
        "oauth_version": "1.0",
    }
    # Query values arrive already encoded in the URL; decode first so each is encoded exactly once.
    pairs = sorted((_pct(unquote(k)), _pct(unquote(v))) for k, v in [*params, *oauth.items()])
    normalized = "&".join(f"{k}={v}" for k, v in pairs)
    base_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    base_string = "&".join([method.upper(), _pct(base_url), _pct(normalized)])
    key = f"{_pct(settings.netsuite_consumer_secret.get_secret_value())}&{_pct(settings.netsuite_token_secret.get_secret_value())}"
    signature = base64.b64encode(hmac.new(key.encode(), base_string.encode(), hashlib.sha256).digest()).decode()
    header = {"realm": settings.netsuite_account_id.upper(), **oauth, "oauth_signature": signature}
    return "OAuth " + ", ".join(f'{k}="{_pct(v)}"' for k, v in header.items())


class NetSuiteSource(ErpSource):
    name = "netsuite"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        required = ("netsuite_account_id", "netsuite_consumer_key", "netsuite_consumer_secret",
                    "netsuite_token_id", "netsuite_token_secret")
        missing = [name.upper() for name in required if not _value(getattr(settings, name))]
        if missing:
            raise SourceError(f"NetSuite is not configured: set {', '.join(missing)}")
        self.settings = settings
        host = settings.netsuite_account_id.lower().replace("_", "-")
        self.endpoint = f"https://{host}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
        self.client = httpx.Client(timeout=120.0, transport=transport)

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def check(self) -> str:
        rows = self._query("SELECT id FROM vendor", limit=1)
        return f"Connected to NetSuite account {self.settings.netsuite_account_id.upper()} ({len(rows)} vendor sampled)"

    def _query(self, sql: str, *, limit: int = _PAGE) -> list[Row]:
        rows: list[Row] = []
        offset = 0
        while True:
            url = f"{self.endpoint}?limit={limit}&offset={offset}"
            try:
                response = self.client.post(
                    url, json={"q": " ".join(sql.split())},
                    headers={
                        "Authorization": oauth_header("POST", url, self.settings),
                        "Prefer": "transient", "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise SourceError(f"Could not reach NetSuite: {exc}") from exc
            if response.status_code >= 400:
                raise SourceError(f"NetSuite rejected the query ({response.status_code}): {_error_text(response)}")
            data = response.json()
            for item in data.get("items", []):
                item.pop("links", None)
                rows.append(item)
            if len(rows) >= _MAX_ROWS:
                raise SourceError(f"NetSuite query returned more than {_MAX_ROWS} rows; narrow it with NETSUITE_QUERY_*")
            if not data.get("hasMore") or limit == 1:
                return rows
            offset += limit

    def fetch(self, dataset: str) -> list[Row]:
        override = getattr(self.settings, f"netsuite_query_{dataset}", "")
        sql = override or DEFAULT_QUERIES.get(dataset)
        if not sql:
            raise SourceError(f"NetSuite has no query for dataset {dataset!r}")
        since = (date.today() - timedelta(days=self.settings.sync_lookback_days)).isoformat()
        sql = sql.replace("{since}", since).replace("{default_lead_time}", str(int(self.settings.default_lead_time_days)))
        return [{k: v for k, v in row.items() if v is not None} for row in self._query(sql)]


def _value(setting: object) -> str:
    return setting.get_secret_value() if hasattr(setting, "get_secret_value") else str(setting)


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
        details = data.get("o:errorDetails") or []
        if details:
            return "; ".join(d.get("detail", "") for d in details)
        return data.get("detail") or data.get("title") or response.text[:200]
    except (ValueError, AttributeError):
        return response.text[:200]
