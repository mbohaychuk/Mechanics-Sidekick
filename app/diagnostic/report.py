from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    system: str
    severity: str  # "good" | "warn" | "fail"
    observation: str
    interpretation: str = ""
    recommendation: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class HealthReport:
    overall_status: str  # "good" | "fair" | "poor"
    summary: str
    findings: list[Finding]


_SEVERITY_RANK = {"good": 0, "warn": 1, "fail": 2}
_OVERALL_BY_RANK = {0: "good", 1: "fair", 2: "poor"}


def derive_overall_status(findings: list[Finding]) -> str:
    worst = max((_SEVERITY_RANK.get(f.severity, 0) for f in findings), default=0)
    return _OVERALL_BY_RANK[worst]


def report_to_json(report: HealthReport) -> dict:
    return {
        "overall_status": report.overall_status,
        "summary": report.summary,
        "findings": [
            {
                "system": f.system,
                "severity": f.severity,
                "observation": f.observation,
                "interpretation": f.interpretation,
                "recommendation": f.recommendation,
                "evidence": f.evidence,
            }
            for f in report.findings
        ],
    }


def report_from_json(d: dict) -> HealthReport:
    return HealthReport(
        overall_status=d.get("overall_status", "good"),
        summary=d.get("summary", ""),
        findings=[
            Finding(
                system=f.get("system", ""),
                severity=f.get("severity", "good"),
                observation=f.get("observation", ""),
                interpretation=f.get("interpretation", ""),
                recommendation=f.get("recommendation", ""),
                evidence=f.get("evidence", {}),
            )
            for f in d.get("findings", [])
        ],
    )
