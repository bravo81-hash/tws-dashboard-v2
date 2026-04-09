import os
import ssl
import urllib.error
import urllib.request
import json


def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


class ClientPortalAdapter:
    def __init__(
        self,
        *,
        enabled=False,
        base_url="https://localhost:5000/v1/api",
        verify_ssl=False,
        timeout_sec=2.0,
    ):
        self.enabled = bool(enabled)
        self.base_url = str(base_url).rstrip("/")
        self.verify_ssl = bool(verify_ssl)
        self.timeout_sec = float(timeout_sec)

    @classmethod
    def from_env(cls):
        return cls(
            enabled=_env_bool("CLIENT_PORTAL_ENABLED", False),
            base_url=os.getenv(
                "CLIENT_PORTAL_BASE_URL", "https://localhost:5000/v1/api"
            ),
            verify_ssl=_env_bool("CLIENT_PORTAL_VERIFY_SSL", False),
            timeout_sec=_env_float("CLIENT_PORTAL_TIMEOUT_SEC", 2.0),
        )

    def health(self):
        payload = {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "verify_ssl": self.verify_ssl,
            "timeout_sec": self.timeout_sec,
            "checked": False,
            "reachable": False,
        }
        if not self.enabled:
            return payload

        payload["checked"] = True
        target_url = f"{self.base_url}/iserver/accounts"
        context = None if self.verify_ssl else ssl._create_unverified_context()

        try:
            request = urllib.request.Request(target_url, method="GET")
            with urllib.request.urlopen(
                request, timeout=self.timeout_sec, context=context
            ) as response:
                payload["reachable"] = True
                payload["status_code"] = getattr(response, "status", None)
        except urllib.error.HTTPError as error:
            # HTTP response still means the gateway is reachable.
            payload["reachable"] = True
            payload["status_code"] = error.code
            payload["error"] = str(error)
        except Exception as error:
            payload["error"] = str(error)

        return payload

    def _request_json(self, path):
        if not self.enabled:
            return {"ok": False, "error": "disabled"}

        normalized_path = str(path or "").lstrip("/")
        target_url = f"{self.base_url}/{normalized_path}"
        context = None if self.verify_ssl else ssl._create_unverified_context()

        try:
            request = urllib.request.Request(target_url, method="GET")
            with urllib.request.urlopen(
                request, timeout=self.timeout_sec, context=context
            ) as response:
                raw = response.read() or b""
                parsed = json.loads(raw.decode("utf-8")) if raw else None
                return {
                    "ok": True,
                    "status_code": getattr(response, "status", None),
                    "data": parsed,
                }
        except urllib.error.HTTPError as error:
            parsed = None
            try:
                raw = error.read() or b""
                parsed = json.loads(raw.decode("utf-8")) if raw else None
            except Exception:
                parsed = None
            return {
                "ok": False,
                "status_code": error.code,
                "data": parsed,
                "error": str(error),
            }
        except Exception as error:
            return {"ok": False, "error": str(error)}

    @staticmethod
    def _parse_float(value):
        try:
            if value is None:
                return None
            if isinstance(value, str):
                value = value.replace(",", "").strip()
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_metric(self, payload, keys):
        if payload is None:
            return None
        wanted = {str(k).lower() for k in keys}

        if isinstance(payload, dict):
            for key, value in payload.items():
                if str(key).lower() in wanted:
                    parsed = self._parse_float(value)
                    if parsed is not None:
                        return parsed
                nested = self._extract_metric(value, keys)
                if nested is not None:
                    return nested
            return None

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    key_name = str(item.get("key", item.get("name", ""))).lower()
                    if key_name in wanted:
                        parsed = self._parse_float(item.get("value"))
                        if parsed is not None:
                            return parsed
                nested = self._extract_metric(item, keys)
                if nested is not None:
                    return nested
            return None

        return None

    def account_risk_context(self, account_id=None):
        payload = {
            "enabled": self.enabled,
            "available": False,
            "account_id": account_id,
            "net_liq": None,
            "maintenance_margin": None,
            "source": None,
        }
        if not self.enabled:
            return payload

        account_info_resp = self._request_json("iserver/accounts")
        if account_info_resp.get("ok"):
            payload["accounts"] = account_info_resp.get("data")
            payload["available"] = True

        candidate_paths = []
        if account_id:
            candidate_paths = [
                f"portfolio/{account_id}/summary",
                f"portfolio/{account_id}/ledger",
            ]
        else:
            candidate_paths = [
                "portfolio/accounts",
            ]

        for path in candidate_paths:
            response = self._request_json(path)
            if not response.get("ok"):
                continue
            data = response.get("data")
            net_liq = self._extract_metric(
                data,
                [
                    "netliquidation",
                    "net_liquidation",
                    "net_liq",
                    "netliq",
                    "netliquidationvalue",
                    "nlv",
                ],
            )
            maintenance = self._extract_metric(
                data,
                [
                    "maintmarginreq",
                    "maintenance_margin",
                    "maintenance_margin_req",
                    "maintmargin",
                    "maintmarginrequirement",
                ],
            )
            if net_liq is not None:
                payload["net_liq"] = net_liq
                payload["source"] = path
            if maintenance is not None:
                payload["maintenance_margin"] = maintenance
            if net_liq is not None or maintenance is not None:
                payload["available"] = True
                break

        return payload
