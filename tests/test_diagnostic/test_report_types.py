from app.diagnostic.report import (
    Finding,
    HealthReport,
    derive_overall_status,
    report_from_json,
    report_to_json,
)


def test_overall_status_derivation():
    assert derive_overall_status([Finding("fuel", "good", "ok")]) == "good"
    assert derive_overall_status([Finding("fuel", "good", "ok"), Finding("o2", "warn", "x")]) == "fair"
    assert derive_overall_status([Finding("cooling", "fail", "hot"), Finding("o2", "warn", "x")]) == "poor"
    assert derive_overall_status([]) == "good"


def test_json_round_trip():
    report = HealthReport(
        overall_status="fair",
        summary="Mostly healthy.",
        findings=[
            Finding("fuel", "warn", "LTFT +14%", interpretation="Lean.",
                    recommendation="Check for a vacuum leak.",
                    evidence={"readings": [{"pid": "LONG_FUEL_TRIM_1", "value": 14.0}],
                              "sources": [{"filename": "m.pdf", "page": 142, "score": 0.5}]}),
        ],
    )
    d = report_to_json(report)
    assert d["overall_status"] == "fair"
    assert d["findings"][0]["recommendation"] == "Check for a vacuum leak."
    back = report_from_json(d)
    assert back.overall_status == "fair"
    assert back.findings[0].evidence["sources"][0]["page"] == 142
    assert back.summary == "Mostly healthy."
