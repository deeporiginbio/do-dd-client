# Deep Origin CLI — Copilot Instructions

Python SDK and CLI for the Deep Origin platform (`deeporigin` package).

## Commands

```bash
uv run ruff format .
uv run ruff check --select I . --fix
uv run pytest --env local -x
uv run pytest tests/test_<module>.py --env local -x
```

Always use `uv run` inside this repo. Tests require `--env local` (mock server) or `--env dev` (live platform).

## Testing

Write **pytest-style** tests. Do not use `unittest.TestCase`.

### Do

- Use plain `def test_*()` functions and `@pytest.fixture` where helpful.
- Use the `client` fixture from [`tests/conftest.py`](../tests/conftest.py) for any code that talks to the platform.
- Run integration tests with `uv run pytest --env local` (autouse mock server on port 4931; see root [`conftest.py`](../conftest.py)).
- Split domains when both unit and integration coverage are needed:
  - `test_<domain>_unit.py` — pure helpers, validation, no network
  - `test_<domain>_local.py` — mock-server integration (`client`, `--env local`)
- Extend the mock server and `tests/fixtures/` when platform behavior is missing — do not stub the client in tests.
- For **external** libraries only (httpx, bokeh, IPython), use library-native test doubles (`httpx.MockTransport`, inject a fake callable, etc.).

### Don't

- `unittest.mock` (`MagicMock`, `@patch`, `patch.object`) on our code or the platform client.
- `monkeypatch` / `pytest.MonkeyPatch` to replace attributes on modules or instances under test.
- `MagicMock(spec=DeepOriginClient)` or mocking `client.executions.create` / `client.tools.get` when the mock server can serve the response.

### Reference tests

| Style | Examples |
|-------|----------|
| Mock-server integration | [`tests/test_rbfe_local.py`](../tests/test_rbfe_local.py), [`tests/test_tools_api.py`](../tests/test_tools_api.py), [`tests/test_abfe_local.py`](../tests/test_abfe_local.py) |
| Pure unit | [`tests/test_fep_common.py`](../tests/test_fep_common.py), [`tests/test_hashing.py`](../tests/test_hashing.py) |
| Hybrid (helpers + `client`) | [`tests/test_results.py`](../tests/test_results.py) |

### Extending the mock server

When adding platform-facing behavior, extend [`tests/mock_server/`](../tests/mock_server/) and fixtures under `tests/fixtures/`. See [`docs/dev/mock-server.md`](../docs/dev/mock-server.md).

## Delivering SDK features

When shipping user-facing SDK capability:

1. Implementation in `src/` / `deeporigin/` following repo style
2. Tests in `tests/` (mock-server routes when needed)
3. Documentation in `docs/`
4. Demo notebook via `docs/notebooks/dirty/` then `./scripts/notebooks.sh` (never edit `docs/notebooks/clean/` directly)

## Common mistakes

- Editing `src/VERSION` or `platform-sdk/src/VERSION` (release CI sets version from git tag)
- Creating notebooks under `docs/notebooks/clean/` directly
- Using `List` / `Dict` instead of `list` / `dict` in type hints
- Running pytest without `--env local` or `--env dev`
