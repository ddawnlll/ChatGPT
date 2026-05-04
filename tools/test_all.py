from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
SUMMARY_PATH = ROOT / "data" / "test-all-summary.md"

CRITICAL_TEST_FILES = [
    "tests/test_tools_shim_regressions.py",
    "tests/test_router_agent_regressions.py",
    "tests/test_streaming_contract.py",
    "tests/test_pi_tool_contract_e2e.py",
    "tests/test_pi_agent_cli_e2e.py",
    "tests/test_fake_playwright_daemon.py",
    "tests/test_fake_playwright_daemon_process.py",
]
BROWSER_TEST_FILES = [
    "tests/test_real_browser_smoke.py",
    "tests/test_real_browser_write_smoke.py",
]
JS_TEST_TARGET = "tools/playwright_transport_helpers.test.mjs"


@dataclass(slots=True)
class StageResult:
    name: str
    priority: str
    critical: bool
    command: list[str]
    includes: list[str]
    status: str
    returncode: int
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    deselected: int = 0
    warnings: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def okay(self) -> bool:
        return self.status in {"passed", "skipped"}


PYTEST_COUNT_PATTERNS = {
    "passed": re.compile(r"(\d+) passed"),
    "failed": re.compile(r"(\d+) failed"),
    "skipped": re.compile(r"(\d+) skipped"),
    "deselected": re.compile(r"(\d+) deselected"),
    "warnings": re.compile(r"(\d+) warnings?"),
}
BUN_COUNT_PATTERNS = {
    "passed": re.compile(r"\n\s*(\d+) pass\b"),
    "failed": re.compile(r"\n\s*(\d+) fail\b"),
}


def discover_noncritical_fast_tests() -> list[str]:
    all_tests = sorted(str(path.relative_to(ROOT)) for path in TESTS_DIR.glob("test_*.py"))
    excluded = set(CRITICAL_TEST_FILES) | set(BROWSER_TEST_FILES)
    return [path for path in all_tests if path not in excluded]


def run_command(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )


def parse_counts(output: str, patterns: dict[str, re.Pattern[str]]) -> dict[str, int]:
    counts: dict[str, int] = {key: 0 for key in patterns}
    for key, pattern in patterns.items():
        match = pattern.search(output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def build_stage_result(*, name: str, priority: str, critical: bool, command: list[str], includes: list[str], completed: subprocess.CompletedProcess[str], parser: str, skipped: bool = False) -> StageResult:
    combined = f"{completed.stdout}\n{completed.stderr}".strip()
    if parser == "pytest":
        counts = parse_counts(combined, PYTEST_COUNT_PATTERNS)
    elif parser == "bun":
        counts = parse_counts(combined, BUN_COUNT_PATTERNS)
        counts.setdefault("skipped", 0)
        counts.setdefault("deselected", 0)
        counts.setdefault("warnings", 0)
    else:
        counts = {"passed": 0, "failed": 0, "skipped": 0, "deselected": 0, "warnings": 0}

    status = "skipped" if skipped else ("passed" if completed.returncode == 0 else "failed")
    return StageResult(
        name=name,
        priority=priority,
        critical=critical,
        command=command,
        includes=includes,
        status=status,
        returncode=completed.returncode,
        passed=counts.get("passed", 0),
        failed=counts.get("failed", 0),
        skipped=counts.get("skipped", 0),
        deselected=counts.get("deselected", 0),
        warnings=counts.get("warnings", 0),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def print_stage_header(title: str) -> None:
    print(f"\n=== {title} ===")


def print_command(command: Iterable[str]) -> None:
    print("$", " ".join(shlex.quote(part) for part in command))


def run_stage(name: str, priority: str, critical: bool, command: list[str], includes: list[str], parser: str) -> StageResult:
    print_stage_header(f"{priority} :: {name}")
    print_command(command)
    completed = run_command(command)
    if completed.stdout.strip():
        print(completed.stdout.rstrip())
    if completed.stderr.strip():
        print(completed.stderr.rstrip(), file=sys.stderr)
    result = build_stage_result(
        name=name,
        priority=priority,
        critical=critical,
        command=command,
        includes=includes,
        completed=completed,
        parser=parser,
    )
    return result


def run_browser_stage() -> StageResult:
    command = [sys.executable, "-m", "pytest", *BROWSER_TEST_FILES, "-q"]
    if os.environ.get("RUN_BROWSER_E2E") == "1":
        return run_stage(
            name="browser_e2e",
            priority="P3 Optional live browser validation",
            critical=False,
            command=command,
            includes=BROWSER_TEST_FILES,
            parser="pytest",
        )

    skipped = subprocess.CompletedProcess(command, 0, stdout="Browser E2E skipped because RUN_BROWSER_E2E is not set to 1.\n", stderr="")
    print_stage_header("P3 Optional live browser validation :: browser_e2e")
    print_command(command)
    print(skipped.stdout.rstrip())
    return build_stage_result(
        name="browser_e2e",
        priority="P3 Optional live browser validation",
        critical=False,
        command=command,
        includes=BROWSER_TEST_FILES,
        completed=skipped,
        parser="pytest",
        skipped=True,
    )


def render_summary(results: list[StageResult]) -> str:
    critical_results = [result for result in results if result.critical]
    optional_results = [result for result in results if not result.critical]
    critical_failed = [result for result in critical_results if result.status == "failed"]
    optional_failed = [result for result in optional_results if result.status == "failed"]

    total_passed = sum(result.passed for result in results)
    total_failed = sum(result.failed for result in results)
    total_skipped = sum(result.skipped for result in results)
    total_deselected = sum(result.deselected for result in results)
    total_warnings = sum(result.warnings for result in results)

    lines: list[str] = []
    lines.append("# Test-All Summary")
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.append(f"- Critical stages failed: {len(critical_failed)}")
    lines.append(f"- Optional stages failed: {len(optional_failed)}")
    lines.append(f"- Total passed assertions/tests reported by runners: {total_passed}")
    lines.append(f"- Total failed assertions/tests reported by runners: {total_failed}")
    lines.append(f"- Total skipped tests reported by runners: {total_skipped}")
    lines.append(f"- Total deselected tests reported by runners: {total_deselected}")
    lines.append(f"- Total warnings reported by runners: {total_warnings}")
    lines.append("")
    lines.append("## Stage Summary")
    lines.append("")
    lines.append("| Stage | Priority | Critical | Status | Passed | Failed | Skipped | Deselected | Warnings |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for result in results:
        lines.append(
            f"| {result.name} | {result.priority} | {'yes' if result.critical else 'no'} | {result.status} | {result.passed} | {result.failed} | {result.skipped} | {result.deselected} | {result.warnings} |"
        )
    lines.append("")
    lines.append("## Critical Stages")
    lines.append("")
    for result in critical_results:
        verdict = "CRITICAL FAIL" if result.status == "failed" else "OK"
        lines.append(f"- **{result.name}**: {verdict}")
        lines.append(f"  - includes: {', '.join(result.includes)}")
        lines.append(f"  - command: `{' '.join(result.command)}`")
    lines.append("")
    lines.append("## Optional Stages")
    lines.append("")
    for result in optional_results:
        verdict = "OPTIONAL FAIL" if result.status == "failed" else result.status.upper()
        lines.append(f"- **{result.name}**: {verdict}")
        lines.append(f"  - includes: {', '.join(result.includes)}")
        lines.append(f"  - command: `{' '.join(result.command)}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- P1 stages are critical: parser, router, pi tool contract, real pi CLI loop, transport protocol, and Bun helper tests.")
    lines.append("- P2 stages are broad fast regression coverage for the remaining Python tests.")
    lines.append("- P3 is optional live browser validation. It is skipped unless `RUN_BROWSER_E2E=1`.")
    return "\n".join(lines) + "\n"


def print_human_summary(results: list[StageResult]) -> None:
    print_stage_header("FINAL SUMMARY")
    for result in results:
        level = "CRITICAL" if result.critical else "OPTIONAL"
        print(
            f"- [{level}] {result.name}: {result.status.upper()} "
            f"(passed={result.passed}, failed={result.failed}, skipped={result.skipped}, deselected={result.deselected}, warnings={result.warnings})"
        )

    critical_failed = [result.name for result in results if result.critical and result.status == "failed"]
    optional_failed = [result.name for result in results if (not result.critical) and result.status == "failed"]

    if critical_failed:
        print(f"\nCritical failures: {', '.join(critical_failed)}")
    else:
        print("\nCritical stages: all okay")

    if optional_failed:
        print(f"Optional stage failures: {', '.join(optional_failed)}")
    else:
        print("Optional stages: all okay or skipped")

    if critical_failed or optional_failed:
        print("Overall result: FAILED")
    else:
        print("Overall result: PASSED")


def main() -> int:
    noncritical_fast_tests = discover_noncritical_fast_tests()
    results: list[StageResult] = []

    results.append(
        run_stage(
            name="bun_js_helpers",
            priority="P1 Critical protocol and helper validation",
            critical=True,
            command=["bun", "run", "test:playwright-helpers"],
            includes=[JS_TEST_TARGET],
            parser="bun",
        )
    )
    results.append(
        run_stage(
            name="critical_pi_proxy_suite",
            priority="P1 Critical protocol and helper validation",
            critical=True,
            command=[sys.executable, "-m", "pytest", *CRITICAL_TEST_FILES, "-q"],
            includes=CRITICAL_TEST_FILES,
            parser="pytest",
        )
    )
    if noncritical_fast_tests:
        results.append(
            run_stage(
                name="broad_fast_suite",
                priority="P2 Broad fast regression coverage",
                critical=False,
                command=[sys.executable, "-m", "pytest", *noncritical_fast_tests, "-q", "-m", "not browser_e2e"],
                includes=noncritical_fast_tests,
                parser="pytest",
            )
        )
    results.append(run_browser_stage())

    summary = render_summary(results)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(summary, encoding="utf-8")
    print_human_summary(results)
    print(f"\nWrote summary: {SUMMARY_PATH}")

    critical_failed = any(result.critical and result.status == "failed" for result in results)
    optional_failed = any((not result.critical) and result.status == "failed" for result in results)
    if critical_failed or optional_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
