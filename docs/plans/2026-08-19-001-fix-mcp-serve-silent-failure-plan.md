# Handoff — `ec mcp serve` 무음 실패 (설치 오진 + try 범위 오류)

- 작성: 2026-08-19
- 작성 맥락: `~/.agents` 세션에서 30일 토큰 사용량 분석 중 발견. 이 저장소에서 별도 세션으로 수정 예정.
- 상태: 미착수 (원인 규명 완료, 코드 미변경)
- 대상 파일: `src/entirecontext/cli/mcp_cmds.py`, `src/entirecontext/mcp/server.py`

## 증상

Claude Code에 등록된 `entirecontext` MCP 서버가 기동되지 않는다. 등록된 12개 리포 전부에서 동일하다.

```
$ cd ~/workspace/resume && ec mcp serve
MCP not available. Install with: pip install 'entirecontext[mcp]'
```

메시지가 "MCP extra를 설치하라"고 안내하지만 **원인 진단이 두 겹으로 틀렸다.**

## 근본 원인

### 1차: uv 툴 venv가 pyproject 대비 stale (환경 문제, 코드 무관)

`pyproject.toml`은 extra를 정상 선언하고 있다.

```toml
[project.optional-dependencies]
mcp = [
    "mcp>=1.0.0",
]
```

설치 receipt도 extra를 포함해 로컬 디렉터리에서 설치했다고 기록한다.

`/Users/teslamint/.local/share/uv/tools/entirecontext/uv-receipt.toml`:

```toml
[tool]
requirements = [{ name = "entirecontext", extras = ["mcp"], directory = "/Users/teslamint/workspace/entirecontext" }]
```

그런데 실제 venv에 MCP SDK가 없다.

```
$ /Users/teslamint/.local/share/uv/tools/entirecontext/bin/python -c \
    "import importlib.metadata as m; print(m.version('mcp'))"
importlib.metadata.PackageNotFoundError: No package metadata was found for mcp

$ ... -c "from mcp.server.fastmcp import FastMCP"
ModuleNotFoundError: No module named 'mcp.server'
```

즉 receipt/pyproject는 맞고 **venv 내용만 뒤처져 있다.** 코드 수정 없이 재설치로 해결된다.

```sh
# 로컬 디렉터리 설치를 유지하면서 재설치 (PyPI로 전환되지 않게 경로 명시)
uv tool install --force 'entirecontext[mcp] @ /Users/teslamint/workspace/entirecontext'
# 또는
uv tool upgrade --reinstall entirecontext
```

주의: `uv tool install --force 'entirecontext[mcp]'`처럼 경로를 빼면 설치 출처가 조용히 PyPI로 바뀐다. 로컬 개발 저장소 연결이 끊기므로 쓰지 말 것.

검증:

```sh
cd ~/workspace/resume && ec mcp serve </dev/null
# 기대: stderr에 "[ec-mcp] starting v0.14.0"
```

### 2차: `try` 범위가 넓어 모든 내부 ImportError를 설치 안내로 오역 (코드 문제)

`src/entirecontext/cli/mcp_cmds.py:12-21`:

```python
@mcp_app.command("serve")
def mcp_serve():
    """Start the MCP server (stdio transport)."""
    try:
        from ..mcp.server import run_server

        run_server()          # ← 호출까지 try 안에 있다
    except ImportError:
        console.print("[red]MCP not available. Install with: pip install 'entirecontext[mcp]'[/red]")
        raise typer.Exit(1)
```

임포트 자체는 **성공한다.** 직접 확인:

```
$ ... -c "from entirecontext.mcp.server import run_server; print('import OK', run_server)"
import OK <function run_server at 0x1019b54e0>
```

실패는 `run_server()` 내부에서 일어나고, `server.py:132-136`이 조용히 반환한다.

```python
def run_server() -> None:
    if mcp is None:
        print("MCP not available. Install with: pip install 'entirecontext[mcp]'")
        return          # ← 종료 코드 0, stdout으로 출력
```

문제점 3가지:

1. **오진**: `run_server()` 내부의 어떤 ImportError(전이 의존성 누락, 버전 불일치, 순환 임포트)도 "extra를 설치하라"로 표시된다. 실제 원인이 은폐된다.
2. **메시지 이중화**: 동일 문구가 `mcp_cmds.py:20`과 `server.py:135` 두 곳에 있다. 후자는 stdout으로 나가 stdio 전송에 오염을 일으킬 수 있다.
3. **무음 성공**: `run_server`가 `return`하므로 종료 코드가 0이다. MCP 클라이언트는 "즉시 정상 종료"로 보고 원인을 알 수 없다. `mcp_cmds.py`를 거치지 않는 호출 경로에서는 실패가 관측 불가능하다.

## 수정 방침

### `mcp_cmds.py` — try를 임포트 문으로만 좁히고, 안내를 정확하게

```python
@mcp_app.command("serve")
def mcp_serve():
    """Start the MCP server (stdio transport)."""
    try:
        from ..mcp.server import run_server
    except ImportError as exc:
        console.print(f"[red]MCP server module import failed: {exc}[/red]")
        console.print("[yellow]Install the extra: uv tool install --force 'entirecontext[mcp] @ <repo path>'[/yellow]")
        raise typer.Exit(1)

    run_server()      # try 밖 — 내부 예외는 그대로 전파
```

핵심: `run_server()`를 `try` 밖으로 빼서 내부 예외가 원래 트레이스백으로 드러나게 한다.

### `server.py` — `run_server`가 실패를 명시적으로 알리게

```python
def run_server() -> None:
    """Run the MCP server (stdio transport)."""
    if mcp is None:
        raise RuntimeError(
            "MCP SDK unavailable: 'from mcp.server.fastmcp import FastMCP' failed. "
            "Install the mcp extra."
        )
    ...
```

- `print()` + `return` → 예외로 교체. 종료 코드가 0이 아니게 되고 stdout이 오염되지 않는다.
- `server.py:11-16`의 `except ImportError: FastMCP = None` 폴백은 유지해도 되지만, **원래 예외를 모듈 변수에 보존**해 `run_server`가 메시지에 포함하면 진단이 쉬워진다.

```python
FastMCP: Any
_FASTMCP_IMPORT_ERROR: ImportError | None = None
try:
    from mcp.server.fastmcp import FastMCP as _FastMCP

    FastMCP = _FastMCP
except ImportError as exc:
    FastMCP = None
    _FASTMCP_IMPORT_ERROR = exc
```

## 수용 기준

1. MCP SDK 없는 환경에서 `ec mcp serve` → **0이 아닌 종료 코드**, stderr에 실제 `ImportError` 메시지 포함, stdout 오염 없음.
2. MCP SDK 있는 환경에서 `ec mcp serve` → stderr `[ec-mcp] starting v<version>`, `tools/list`가 `ec_*` 도구 29개 반환.
3. `run_server()` 내부에서 임의의 `ImportError`를 발생시켜도 "install the extra" 문구로 대체되지 않고 원래 트레이스백이 보인다 — 회귀 테스트로 고정할 것.
4. `MCP not available` 문구가 코드베이스에 한 곳만 남는다.

## 테스트 제안

`tests/`에 다음을 추가한다. 3번이 실제 버그를 잡는 유일한 테스트이므로 반드시 포함할 것.

- `run_server`를 `mcp = None` 상태로 호출 → `RuntimeError` 발생 확인
- `mcp_serve`가 임포트 실패 시 `typer.Exit(1)` 확인
- `run_server`를 `ImportError("boom")`를 던지도록 monkeypatch → `mcp_serve`가 "install the extra"로 삼키지 않고 전파함을 확인

## 영향 및 우선순위 근거

MCP 경로만 죽어 있고 **데이터 수집은 정상**이다 (`ec repo list`: 12개 리포 등록, `resume` 3,786 세션 / 6,278 턴, `entirecontext` 1,855 / 3,205). 따라서 데이터 손실은 없고, 잃고 있는 것은 에이전트의 메모리 재사용 경로뿐이다.

토큰 비용 측면 계측치 (30일, Claude Code 세션 로그 기준):

- 비용 상위 2개 프로젝트가 `resume` 36.9% + `cogvault` 17.1% = **54%** — EntireContext 데이터가 가장 많이 쌓인 리포와 정확히 일치
- MCP 재활성화 시 도구 정의 29개가 프롬프트 프리픽스에 추가: **약 2,718 tok/호출** (정적 추정, 설치 후 실측 필요) = 입력 볼륨 +1.6%
- 반대급부로 `Read` 재탐색 감소 기대. `Read` 결과는 텍스트 도구 페이로드의 37.3%, 같은 세션 내 동일 경로 재독이 Read 호출의 41.5%

즉 **1.6% 프리픽스 비용으로 메모리 재사용을 사는 거래**이며, 손익분기점은 낮다고 판단했다. 설치 후 `ec_*` 도구 정의 실제 바이트를 재측정해 2,718 tok 추정치를 확정할 것.

## 착수 순서

1. 재설치 (경로 명시) → `[ec-mcp] starting` 확인. 여기서 증상은 사라진다.
2. `tools/list` 29개 확인 + 도구 정의 실제 바이트 측정.
3. 코드 수정 (`mcp_cmds.py` try 범위, `server.py` 예외화) + 회귀 테스트 3개.
4. 다음 환경 드리프트를 조기에 잡을 수단 검토 — `ec doctor`류 자기점검에 "MCP SDK 임포트 가능 여부" 추가.

1번만으로 기능은 복구되지만, 2차 원인을 고치지 않으면 **다음 환경 드리프트에서 똑같이 오진**된다. 3번까지 완료할 것.
