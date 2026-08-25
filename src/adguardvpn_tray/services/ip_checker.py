import json
import urllib.request

_URL = "https://api64.ipify.org?format=json"


def get_public_ip(timeout: float = 5.0) -> str | None:
    try:
        with urllib.request.urlopen(_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ip")
    except Exception:
        return None
