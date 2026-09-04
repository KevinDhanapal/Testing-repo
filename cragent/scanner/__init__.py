from cragent.scanner.shared_state import scan_paths as scan_shared_state
from cragent.scanner.lazy_init import scan_paths as scan_lazy_init
from cragent.scanner.async_blocking import scan_paths as scan_async_blocking
from cragent.scanner.executor_service import scan_paths as scan_executor_service
from cragent.scanner.lock_order import scan_paths as scan_lock_order
from cragent.scanner.hot_path import scan_paths as scan_hot_path

__all__ = ['scan_paths']


def scan_paths(paths):
    findings = []
    findings.extend(scan_shared_state(paths))
    findings.extend(scan_lazy_init(paths))
    findings.extend(scan_async_blocking(paths))
    findings.extend(scan_executor_service(paths))
    findings.extend(scan_lock_order(paths))
    findings.extend(scan_hot_path(paths))
    return findings
