# netlag-monitor

[![CI](https://github.com/guifqz/netlag-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/guifqz/netlag-monitor/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **EN:** CLI that measures latency, jitter, packet loss and bufferbloat against several targets (gateway, DNS, game-server regions) and explains the result in plain language.
> It exports CSV and a self-contained HTML report, and runs on Windows, Linux and macOS without admin rights.

Diagnóstico de rede para quem joga online ou trabalha de casa. O `netlag` mede **latência, jitter, perda de pacotes e bufferbloat** contra vários alvos ao mesmo tempo, mostra uma tabela ao vivo no terminal e aponta a provável causa do problema (Wi-Fi, provedor, rota ou fila do roteador).

## Motivação

Input lag e rubber-banding em jogo online quase nunca são "a internet está lenta". O mais comum é:

- **Jitter e perda no Wi-Fi**: o ping médio parece bom, mas os picos derrubam o tickrate.
- **Bufferbloat**: o roteador enfileira pacotes quando alguém baixa algo ou entra em call, e o ping vai de 15 ms para 200 ms.
- **Rota ruim até o servidor do jogo**: latência alta só para uma região específica.

Esses problemas não aparecem em teste de velocidade. Em home office eles viram travadas em videochamada. A ideia do projeto é separar, com medições simples, **onde** está o problema: na rede local, no provedor ou no caminho até o destino.

## Instalação

Requer Python 3.11 ou superior.

```bash
pip install git+https://github.com/guifqz/netlag-monitor.git
```

Ou, para desenvolver:

```bash
git clone https://github.com/guifqz/netlag-monitor.git
cd netlag-monitor
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
```

## Uso

```bash
netlag                      # gateway, 1.1.1.1, 8.8.8.8 e AWS sa-east-1; 30 rodadas
netlag -c 120 -i 0.5        # 120 rodadas, uma a cada 0,5 s
netlag -c 0                 # roda até Ctrl+C
netlag -t gateway cloudflare meuservidor.com:27015
netlag --bufferbloat        # inclui o teste de bufferbloat
netlag -c 60 --csv medicao.csv --html relatorio.html
netlag targets              # lista os alvos pré-definidos
```

Exemplo de saída (ilustrativo, rede doméstica com Wi-Fi instável):

```text
netlag

 Alvo            Via    Últ.    Min   Média    p95   Jitter   Perda    N
 ───────────────────────────────────────────────────────────────────────
 gateway         ping    2.0    1.0     4.8   19.0      5.6    6.7%   60
 cloudflare      ping   13.0   11.0    13.1   15.0      1.4    0.0%   60
 google          ping   15.0   13.0    15.4   18.0      1.6    0.0%   60
 aws-sa-east-1   tcp    22.4   20.1    22.9   26.3      1.8    0.0%   60

Bufferbloat
 Fase          Média (ms)   p95 (ms)   Jitter (ms)   Perda
 ─────────────────────────────────────────────────────────
 repouso             13.2       15.0           0.9    0.0%
 sob carga          168.5      240.0          15.5    1.9%
 Aumento de 155.3 ms com 90 Mbps de carga: nota E

Diagnóstico
[ATENÇÃO] Perda de 6.7% só no gateway, sem perda na internet: problema na rede
local. Verifique sinal e interferência do Wi-Fi, troque o cabo Ethernet ou teste
outra porta do roteador.
[ATENÇÃO] Bufferbloat nota E: latência média subiu 155 ms sob carga (13 -> 169
ms; jitter 0.9 -> 15.5 ms). Downloads e streams vão causar lag no jogo. Ative
SQM (fq_codel/CAKE) no roteador ou limite a banda em ~90% da velocidade
contratada via QoS.
```

Um relatório HTML de exemplo (dados fictícios, gerado por `scripts/gerar_exemplo.py`) está em [`docs/exemplo-relatorio.html`](docs/exemplo-relatorio.html). Baixe e abra no navegador; o arquivo é autocontido, sem CDN nem JavaScript.

### Opções principais

| Opção | Descrição |
|---|---|
| `-t, --targets` | Presets (`gateway`, `cloudflare`, `google`, `aws-sa-east-1`, `aws-us-east-1`, `aws-us-west-2`, `aws-eu-west-1`), `host` (ICMP) ou `host:porta` (TCP) |
| `-c, --count` | Rodadas de medição (`0` = até Ctrl+C) |
| `-i, --interval` | Segundos entre rodadas |
| `-m, --method` | `auto` (padrão), `ping` ou `tcp` |
| `--csv`, `--html` | Exporta amostras e relatório |
| `--bufferbloat` | Roda o teste de bufferbloat (`--load-url`, `--load-threads`, `--idle-seconds`, `--load-seconds`, `--bufferbloat-target`) |

A URL de carga padrão baixa um arquivo de 100 MB de um servidor público. Para um teste mais fiel, aponte `--load-url` para um arquivo grande hospedado perto de você. O teste só mede latência; o download é descartado.

## Como as métricas são calculadas

- **Sonda ICMP**: chama o `ping` do sistema (um pacote por rodada) e extrai o RTT com regex tolerante a idioma (`time=`, `tempo=`, `tiempo=`, `Zeit=`, vírgula decimal, `<1ms` do Windows). Funciona sem privilégios de administrador.
- **Sonda TCP**: mede o tempo do handshake (`connect`) com o DNS resolvido uma única vez, para não somar a resolução ao RTT. Uma conexão recusada (RST) também conta como resposta, pois o pacote foi e voltou. É o método padrão para os endpoints AWS (`dynamodb.<região>.amazonaws.com:443`), que normalmente não respondem a ICMP, e o fallback quando `ping` não existe.
- **Perda %**: amostras sem resposta no timeout dividido pelo total enviado.
- **min / avg / max**: sobre as amostras que responderam.
- **p50 / p95 / p99**: percentis com interpolação linear entre vizinhos (mesmo método padrão do NumPy).
- **Jitter**: média da diferença absoluta entre amostras consecutivas que responderam, `mean(|rtt[i] - rtt[i-1]|)`, no espírito da RFC 3550 (que usa uma média móvel exponencial dessa mesma diferença).
- **Gateway**: detectado por `route print -4` (Windows), `ip route show default` (Linux) ou `route -n get default` (macOS).

### Bufferbloat

1. Mede o alvo em **repouso** (padrão: 8 s, uma sonda a cada 250 ms).
2. Inicia 4 threads baixando `--load-url` em loop, aguarda 2 s para a carga estabilizar e mede **sob carga** (padrão: 12 s).
3. A nota usa o aumento da latência média sob carga:

| Aumento | Nota |
|---|---|
| < 15 ms | A |
| < 30 ms | B |
| < 60 ms | C |
| < 120 ms | D |
| < 200 ms | E |
| ≥ 200 ms | F |

O teste é inconclusivo, e avisa, se nada foi baixado ou se o alvo parou de responder.

### Diagnóstico

Regras simples e transparentes em [`netlag/diagnosis.py`](netlag/diagnosis.py), com limiares em constantes no topo do arquivo. Por exemplo:

- perda só no gateway: Wi-Fi, cabo ou porta do roteador;
- perda no gateway e na internet: resolver a rede local primeiro;
- perda só na internet, com gateway limpo: provedor ou rota;
- jitter alto até o gateway: Wi-Fi congestionado (prefira cabo ou 5 GHz);
- latência alta só para uma região distante: roteamento;
- bufferbloat D, E ou F: ativar SQM (fq_codel/CAKE) ou QoS.

Com menos de 10 amostras por alvo o diagnóstico avisa que o resultado é pouco confiável.

## Desenvolvimento

```bash
pytest          # parsers (Windows pt-BR/en/es/de, Linux, macOS), estatísticas, notas, diagnóstico, relatório
ruff check . && ruff format --check .
python scripts/gerar_exemplo.py   # regenera docs/exemplo-relatorio.html
```

O CI roda ruff e pytest em `ubuntu-latest` e `windows-latest` com Python 3.12.

## Limitações

- Uma sonda ICMP por rodada usa um processo `ping`; com intervalos abaixo de ~0,2 s o custo do processo começa a aparecer na medição.
- Saída de `ping` em idiomas fora de pt, en, es, de e fr pode não ser reconhecida; use `--method tcp` nesse caso.
- Em TCP, roteadores que descartam (em vez de recusar) conexões na porta 443 aparecem como perda; para o gateway prefira ICMP.

## Licença

[MIT](LICENSE) © 2026 Guilherme
