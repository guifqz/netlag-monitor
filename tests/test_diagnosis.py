from netlag.bufferbloat import BufferbloatResult
from netlag.diagnosis import Diagnosis, diagnose
from netlag.stats import Sample, summarize
from netlag.targets import Target, TargetResult


def make(name: str, kind: str, samples: list[Sample]) -> TargetResult:
    result = TargetResult(Target(name, f"{name}.test", kind=kind))  # type: ignore[arg-type]
    for index, sample in enumerate(samples):
        result.add(float(index), sample)
    return result


def steady(value: float = 10.0, n: int = 40, lost_every: int = 0) -> list[Sample]:
    return [None if lost_every and i % lost_every == 0 else value + (i % 2) * 0.5 for i in range(n)]


def bloat(idle_avg: float, loaded_avg: float, grade: str) -> BufferbloatResult:
    return BufferbloatResult(
        idle=summarize([idle_avg, idle_avg + 1]),
        loaded=summarize([loaded_avg, loaded_avg + 40]),
        delta_ms=loaded_avg - idle_avg,
        grade=grade,
        mbps=95.0,
    )


def messages(findings: list[Diagnosis], level: str) -> list[str]:
    return [f.message for f in findings if f.level == level]


def test_healthy_network_is_ok() -> None:
    findings = diagnose(
        [make("gateway", "gateway", steady(2)), make("cloudflare", "dns", steady(12))]
    )
    assert [f.level for f in findings] == ["ok"]


def test_loss_only_on_gateway_points_to_local_network() -> None:
    findings = diagnose(
        [make("gateway", "gateway", steady(2, lost_every=5)), make("cloudflare", "dns", steady(12))]
    )
    warnings = messages(findings, "crit") + messages(findings, "warn")
    assert len(warnings) == 1
    assert "só no gateway" in warnings[0]
    assert "Wi-Fi" in warnings[0]


def test_loss_on_gateway_and_internet_blames_local_first() -> None:
    findings = diagnose(
        [
            make("gateway", "gateway", steady(2, lost_every=5)),
            make("cloudflare", "dns", steady(12, lost_every=4)),
        ]
    )
    text = " ".join(messages(findings, "crit"))
    assert "já no gateway" in text


def test_loss_only_on_internet_points_to_isp() -> None:
    findings = diagnose(
        [
            make("gateway", "gateway", steady(2)),
            make("cloudflare", "dns", steady(12, lost_every=40)),
        ]
    )
    text = " ".join(messages(findings, "warn"))
    assert "provedor" in text
    assert "cloudflare" in text


def test_high_gateway_jitter_suggests_cable_or_5ghz() -> None:
    wobbly = [2.0, 25.0] * 20
    findings = diagnose([make("gateway", "gateway", wobbly), make("cloudflare", "dns", steady(12))])
    assert any("5 GHz" in m for m in messages(findings, "warn"))


def test_high_internet_jitter_with_stable_gateway() -> None:
    wobbly = [10.0, 60.0] * 20
    findings = diagnose([make("gateway", "gateway", steady(2)), make("google", "dns", wobbly)])
    assert any("google" in m and "provedor" in m for m in messages(findings, "warn"))


def test_high_latency_only_to_far_region_is_routing_info() -> None:
    findings = diagnose(
        [
            make("gateway", "gateway", steady(2)),
            make("cloudflare", "dns", steady(12)),
            make("aws-eu-west-1", "region", steady(240)),
        ]
    )
    info = messages(findings, "info")
    assert len(info) == 1
    assert "aws-eu-west-1" in info[0]
    assert "roteamento" in info[0]
    assert not messages(findings, "warn")


def test_bufferbloat_bad_grade_suggests_sqm() -> None:
    findings = diagnose([make("cloudflare", "dns", steady(12))], bloat(12, 230, "F"))
    critical = messages(findings, "crit")
    assert len(critical) == 1
    assert "SQM" in critical[0]
    assert "Bufferbloat nota F" in critical[0]


def test_bufferbloat_good_grade_adds_nothing() -> None:
    findings = diagnose([make("cloudflare", "dns", steady(12))], bloat(12, 18, "A"))
    assert [f.level for f in findings] == ["ok"]


def test_unreachable_target_suggests_tcp() -> None:
    findings = diagnose(
        [make("aws-sa-east-1", "region", [None] * 12), make("cloudflare", "dns", steady(12))]
    )
    assert any("--method tcp" in m for m in messages(findings, "crit"))


def test_few_samples_warns_about_confidence() -> None:
    findings = diagnose([make("cloudflare", "dns", steady(12, n=4))])
    assert any("Poucas amostras" in m for m in messages(findings, "info"))
    assert not any(f.level == "ok" for f in findings)
