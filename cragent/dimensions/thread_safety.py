"""Thread safety: JVM concurrency, Python GIL/threading, JS event-loop races."""
from __future__ import annotations

import re
from typing import List

from cragent.dimensions._common import clean_source, code_lines
from cragent.dimensions._java_scanners import findings_for_category, fix_hint
from cragent.dimensions.base import Dimension
from cragent.engine.models import FileContext, Finding, CRITICAL, MAJOR, MINOR, normalize_severity

THREADING_HINT = re.compile(r"\b(?:threading|concurrent\.futures|multiprocessing\.dummy|asyncio)\b")


class ThreadSafety(Dimension):
    key = "thread_safety"
    label = "Thread Safety"

    def rules_java(self, ctx: FileContext) -> List[Finding]:
        findings: List[Finding] = []
        for raw in findings_for_category(ctx.path, "Thread-Safety"):
            findings.append(Finding(
                dimension=self.key,
                rule=str(raw.get("rule") or "concurrency_issue"),
                file=ctx.rel_path,
                language=ctx.language,
                line=int(raw.get("line") or 0),
                severity=normalize_severity(raw.get("severity")),
                issue=str(raw.get("reason") or "Potential concurrency issue"),
                fix=str(raw.get("recommendation") or fix_hint(
                    raw.get("reason", ""),
                    "Guard shared mutable state with synchronization or immutable data.")),
                snippet=str(raw.get("code_snippet") or ""),
            ))
        source = clean_source(ctx)
        if re.search(r"\b(?:SimpleDateFormat|Calendar)\s+\w+\s*=", source) and re.search(
            r"(?m)^\s*(?:private|public|protected)?\s*static\s+.*SimpleDateFormat", source
        ):
            line = source.count("\n", 0, source.find("SimpleDateFormat")) + 1
            findings.append(self.finding(
                ctx, "non_thread_safe_formatter", line, CRITICAL,
                "SimpleDateFormat held in a static field is not thread-safe",
                "Use DateTimeFormatter, or create the formatter per invocation.",
            ))
        for number, text in code_lines(ctx):
            if re.search(r"(?:HashMap|ArrayList|HashSet)\s*<[^>]*>\s*\w+\s*=", text) and "static" in text:
                findings.append(self.finding(
                    ctx, "unsynchronized_shared_collection", number, MAJOR,
                    "Static mutable collection is shared across threads without synchronization",
                    "Use ConcurrentHashMap/CopyOnWriteArrayList, or make it immutable.",
                ))
        return findings

    def rules_python(self, ctx: FileContext) -> List[Finding]:
        findings: List[Finding] = []
        if not THREADING_HINT.search(ctx.source):
            return findings
        uses_lock = re.search(r"\b(?:Lock|RLock|Semaphore|Condition)\s*\(", ctx.source) is not None
        for number, text in code_lines(ctx):
            stripped = text.strip()
            if stripped.startswith("global ") and not uses_lock:
                findings.append(self.finding(
                    ctx, "unguarded_global_mutation", number, MAJOR,
                    "Module-level state is mutated from threaded code without a lock",
                    "Protect the update with threading.Lock, or use queue.Queue for hand-off.",
                ))
            if re.search(r"\w+\s*\+=\s*1", stripped) and not uses_lock and "self." in stripped:
                findings.append(self.finding(
                    ctx, "non_atomic_counter", number, MAJOR,
                    "Read-modify-write on shared state is not atomic despite the GIL",
                    "Use itertools.count, a lock, or an atomic queue.",
                ))
            if re.search(r"threading\.Thread\s*\(", stripped) and ".join(" not in ctx.source:
                findings.append(self.finding(
                    ctx, "unjoined_thread", number, MINOR,
                    "Thread is started but never joined",
                    "Join the thread, or use concurrent.futures.ThreadPoolExecutor as a context manager.",
                ))
            if re.search(r"time\.sleep\s*\(", stripped) and "async def" in ctx.source:
                findings.append(self.finding(
                    ctx, "blocking_call_in_async", number, CRITICAL,
                    "Blocking time.sleep() inside an async module stalls the event loop",
                    "Use await asyncio.sleep(), or run blocking work in an executor.",
                ))
        return findings

    def rules_javascript(self, ctx: FileContext) -> List[Finding]:
        findings: List[Finding] = []
        module_state = set(re.findall(r"(?m)^\s*(?:let|var)\s+([A-Za-z_$][\w$]*)", ctx.source))
        parsed = ctx.parsed()
        for function in parsed.functions:
            if "await" not in function.body:
                continue
            for name in module_state:
                pattern = re.compile(rf"\b{re.escape(name)}\s*(?:\+\+|--|[-+*/]?=)")
                if pattern.search(function.body):
                    findings.append(self.finding(
                        ctx, "shared_state_across_await", function.line, MAJOR,
                        f"Module-level '{name}' is mutated in async function '{function.name}'; "
                        "interleaved calls can observe a torn value",
                        "Keep the state inside the call scope, or serialize access with a mutex/queue.",
                        function.signature,
                    ))
                    break
        for number, text in code_lines(ctx):
            if re.search(r"(?:readFileSync|writeFileSync|execSync)\s*\(", text):
                findings.append(self.finding(
                    ctx, "blocking_event_loop", number, MAJOR,
                    "Synchronous I/O blocks the single-threaded event loop",
                    "Use the promise-based async API instead.",
                ))
        return findings
