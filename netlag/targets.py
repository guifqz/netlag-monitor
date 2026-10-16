"""Alvos de medição: presets e hosts personalizados."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from netlag.stats import Sample, Stats, summarize

Kind = Literal["gateway", "dns", "region", "custom"]
Method = Literal["ping", "tcp"]

DEFAULT_TCP_PORT = 443
DEFAULT_PRESETS = ("gateway", "cloudflare", "google", "aws-sa-east-1")


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    host: str
    kind: Kind = "custom"
    method: Method = "ping"
    port: int = DEFAULT_TCP_PORT
    description: str = ""


@dataclass(slots=True)
class TargetResult:
    """Série de medições de um alvo; `samples` usa None para pacote perdido."""

    target: Target
    method: Method = "ping"
    samples: list[Sample] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)

    def add(self, timestamp: float, sample: Sample) -> None:
        self.timestamps.append(timestamp)
        self.samples.append(sample)

    @property
    def stats(self) -> Stats:
        return summarize(self.samples)

    @property
    def last(self) -> float | None:
        return self.samples[-1] if self.samples else None


def _aws(region: str, place: str) -> Target:
    return Target(
        name=f"aws-{region}",
        host=f"dynamodb.{region}.amazonaws.com",
        kind="region",
        method="tcp",
        description=f"AWS {region} ({place}), TCP 443",
    )


PRESETS: dict[str, Target] = {
    "cloudflare": Target("cloudflare", "1.1.1.1", kind="dns", description="Cloudflare DNS"),
    "google": Target("google", "8.8.8.8", kind="dns", description="Google DNS"),
    "aws-sa-east-1": _aws("sa-east-1", "São Paulo"),
    "aws-us-east-1": _aws("us-east-1", "Virginia"),
    "aws-us-west-2": _aws("us-west-2", "Oregon"),
    "aws-eu-west-1": _aws("eu-west-1", "Irlanda"),
}

GATEWAY_NAME = "gateway"


def parse_target(spec: str) -> Target:
    """Interpreta `host` (ICMP) ou `host:porta` (TCP) como alvo personalizado."""
    spec = spec.strip()
    if not spec:
        raise ValueError("alvo vazio")
    host, sep, port = spec.rpartition(":")
    if sep and host and ":" not in host and port.isdigit():
        number = int(port)
        if not 0 < number < 65536:
            raise ValueError(f"porta inválida em '{spec}'")
        return Target(name=spec, host=host, method="tcp", port=number)
    return Target(name=spec, host=spec)
