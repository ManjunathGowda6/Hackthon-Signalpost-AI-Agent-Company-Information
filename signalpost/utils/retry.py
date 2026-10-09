"""Retry utilities."""
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
def async_retry(max_attempts=3, backoff_base=1.0, exceptions=(Exception,)):
    return retry(stop=stop_after_attempt(max_attempts),
                 wait=wait_exponential(multiplier=backoff_base, min=1, max=30),
                 retry=retry_if_exception_type(exceptions), reraise=True)
