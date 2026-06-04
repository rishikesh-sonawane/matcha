import time

from requests.exceptions import ConnectionError, Timeout

RETRYABLE_STATUSES = {429, 502, 503, 504}


def resilient_get(url, session=None, **kwargs):
    http = session
    if http is None:
        import requests

        http = requests
    timeout = kwargs.pop("timeout", 15)
    for attempt in range(3):
        try:
            resp = http.get(url, timeout=timeout, **kwargs)
            if resp.status_code in RETRYABLE_STATUSES and attempt < 2:
                time.sleep(2**attempt)
                continue
            return resp
        except (ConnectionError, Timeout):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    return http.get(url, timeout=timeout, **kwargs)
