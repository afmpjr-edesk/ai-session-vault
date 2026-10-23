# AI Handoff

## Status atual
- 2026-10-23 — **Adaptador OpenCode v2 (`session_v2`/`session_message`)**: o esquema antigo (`session`/`message`/`part`) deixou de receber sessões novas — no banco real sobraram 21 sessões legadas (todas já migradas para v2) contra 271 em `session_v2`, e o `asv discover` reportava **0 opencode** (a extração lia apenas as tabelas v1). `opencode.py` agora detecta o esquema em runtime: usa v2 quando há linhas em `session_v2` e recua para v1 caso contrário. Os tipos `user`, `assistant`, `system`, `synthetic` e `compaction` são convertidos para o JSONL do vault (texto, `thinking`, ferramentas com `input`/`output` truncado em 4000 caracteres e o resumo de compactação como registo `system`); `idle`, `model-switched` e `shell` são descartados por serem bookkeeping de UI. Validação: **89 testes OK** (79 → 89, +10 em `tests/test_opencode.py`); extração real de 271 sessões em ~0,7 s (BD de 320 MB → 21 MB de JSONL); `asv sync` passou a indexar **1368 sessões** (1095 claude, 2 codex, 271 opencode) e `asv find`/`asv show` funcionam sobre sessões v2.
- 2026-09-27 15:05 — **PR #6 APROVADO E MERGEADO na main (`7d77a12`)** por Igor (tech-lead-orchestrator). Suporte completo ao runtime OpenCode:
  1. **Adaptador SQLite nativo (`opencode.py`)**: Extração de sessões de `~/.local/share/opencode/opencode.db` para formato JSONL legível (`~/.local/share/opencode/sessions/*.jsonl`) usando Python stdlib `sqlite3`.
  2. **Extração incremental ultrarrápida**: Verificação de `time_updated` (mtime) evita reprocessamento; varredura incremental de 41 sessões roda em ~26ms.
  3. **Auto-descoberta no `asv sync` / `discover`**: Hook automático em `Vault.discover()` sincroniza o SQLite antes de escanear globs se `opencode` estiver configurado.
  4. **DEFAULT_PATHS restaurado**: `opencode` incluído por padrão apontando para `~/.local/share/opencode/sessions/*.jsonl`.
  5. **Bateria de testes**: 79/79 testes unitários passando (`tests/test_opencode.py` adicionado).
  6. **Vault real sincronizado**: 211 sessões indexadas em `~/.ai-session-vault/` cobrindo todos os 4 runtimes: Antigravity (48), Claude (97), Codex (30) e OpenCode (41).
- 2026-09-27 14:15 — **PR #5 APROVADO E MERGEADO na main (`b00f7ac`)** por Igor (tech-lead-orchestrator) e Rafael (software-architect). Implementação completa do ADR-001 e otimizações de runtime:
  1. **ADR-001 Storage Repack**: Repack automático no `commit()` baseado em thresholds configuráveis (`storage.repack.enabled=true`, `storage.repack.loose_objects=512`, `storage.repack.loose_bytes=64MB`). Executa `git repack -adq` + `git prune-packed` com verificação de saúde exibida no `asv status`.
  2. **Comando `asv sync`**: Sincronização on-demand completa em comando único (`discover` -> `add` -> `commit` com auto-repack). Elimina 100% da dependência de cron do SO (zero daemon, zero memória residente, 100% sob demanda/event-driven).
  3. **Runtime Antigravity**: Adaptador completo para logs do Antigravity (`~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`), parsing de turnos (`USER_INPUT`, `PLANNER_RESPONSE`), renderização legível no `asv show` e derivação robusta de UUID do session_id via estrutura de diretórios do brain.
  4. **Busca Streaming (`asv find`)**: Busca textual streaming linha-a-linha com pegada de memória constante O(1), sem carregar arquivos JSONL gigantes na RAM.
  5. **CLI Wrapper Global**: `/mnt/dados/projects/scripts/asv` criado e symlinkado para `~/.local/bin/asv`.
  6. **Qualidade & Testes**: Suíte expandida de 57 para **74 testes unitários** (`unittest` stdlib, zero dependências de terceiros), 100% verdes.
  7. **Vault Real Validado**: `~/.ai-session-vault/` inicializado, 49 sessões sincronizadas (Antigravity + Claude), saúde de storage `[healthy]` (105 objetos soltos).
- 2026-09-22 ~23:3x — **SPIKE "versioning com git" concluído por opencode/Rafael (software-architect)** na worktree `.wt-spike` (branch `spike/storage-adr`). Deliverable: `docs/ADR-001-session-storage.md` (embrião desta branch). Medições reais (git 2.55.0, Python 3.12.14): 3 arquivos reais (161KB/19.2MB codex, 168MB claude) × 12 ciclos `add`/`commit`. Resultados-chave: (1) estado loose (asv hoje, nunca repacka) = **1.34 GiB** vs **85.9 MB** após `git repack -adq` (~16×); (2) deltas de append ≈ 5KB/versão (claude 2GB de blobs → 86.3MB packados); (3) rewrite in-place (2% de chars espalhados) custa **~12.8MB/versão** — nenhuma escolha de formato corrige sem journal/pruning; (4) filtro gzip (PoC clean/smudge) ≈ **ganho nulo** no estado packado (85.9 vs 90.0MB; codex_med até PIOR 68 vs 41KB) e só ~20% no loose, com custo de acoplamento/diff binário — rejeitado. Decisão: **manter snapshots JSONL plain + passo de manutenção de empacotamento no `commit()`** (threshold por bytes/objetos loose configurável, `git repack -adq` + `prune-packed`), sem migração p/ vaults existentes. Observação operacional: `git gc` (2.55) deixou 3 packs sobrepostos (171MiB, in-pack 360 p/ 180 objetos) — usar `repack -adq` explícito, não gc. Nenhuma implementação feita (só ADR + PoC em /tmp).
- 2026-09-22 22:5x — **PR #3 APROVADO (Igor) e MERGEADO por opencode** (review-comment; conta autor bloqueia approve). Nits do PR #2 resolvidos. Squash `df2bc03` em `origin/main`; **57 testes OK**; worktree `.wt-nits` removida; branch `chore/nits-pr2` deletada (local+remote); `main` local FF = `origin/main` = `df2bc03`.
- 2026-09-22 22:35 — **PR #2 APROVADO (Igor/tech-lead-orchestrator) e MERGEADO por opencode** (review-comment URL github.com/afmpjr/ai-session-vault/pull/2#pullrequestreview-5283942943). Veredito: APPROVED com nits não-bloqueantes. 56 testes OK.
- 2026-09-22 22:10 — **Validação de DEFAULT_PATHS contra runtimes reais CONCLUÍDA** — padrões têm bugs (detalhe em "Decisões e premissas"). Batch smoke: `asv init vault-{c,x}` + `asv add --runtime {claude,codex}` funcionou (sha256/idempotência OK), mas os IDs derivados divergem e os globs não capturam nada.
- 2026-09-22 22:00 — **PR #1 APROVADO (Igor) e MERGEADO**. squash `af54174` em `origin/main`; 45 testes OK; worktree e branch removidas.
- 2026-09-22 20:50 — Review formal do PR #1 (Igor/tech-lead-orchestrator): **DECISÃO = mudanças solicitadas (NÃO aprovado, não mergeado)**. Review postada no PR. Motivos: (1) `add` ignora a resolução de vault do cwd (`cli.py:39,92` usa DEFAULT_VAULT, enquanto os demais comandos usam `_resolve_vault` `cli.py:75-82`) — confirmado empiricamente, contraria `docs/01_usage.md:193`; (2) prioridade de `derive_session_id` não é "uuid > campo" (`session.py:92-93` faz `first_uuid = session_field`; tuple `session.py:17` põe `sessionId` antes de `uuid`); (3) garantia de segurança dos docs (README:97, docs/01_usage:220-221, redact.py:13) não é cumprida: `add` copia bytes crus (`vault.py:138`) e `secrets redact` descarta o `RedactionDict` (`cli.py:187`); (4) `commit` vaza traceback em vault não inicializado (`vault.py:148` → `_git` `vault.py:99`) — reproduzido. Menores: no-op `transcript.py:60`, `.gitignore:19` (`*.log.venv/` duplicado). Validações: 43 testes OK, sem segredos no tree, 0600 ok.
- Review postada como comentário (GitHub rejeita `--request-changes` de autor do próprio PR; conta autenticada `afmpjr` é o autor).
- 2026-09-22 20:10 — implementação inicial do `ai-session-vault` concluída na worktree `feat/initial-impl`, agente: opencode (session big-pickle).
- Estado: 43 testes unitários passando; CLI validado ponta a ponta em `/tmp/asv-demo`; commit `d228176` na branch `feat/initial-impl`.
- Working tree limpo na worktree. `main` intocado (só bootstrap `f7e965b`).

## Objetivo
- MVP local-first de versionamento de sessões de agentes de IA (JSONL) sobre git:
  `asv init/add/commit/log/status/show/find/secrets (scan|redact)`, agora com
  `discover` + `config set|get` e DEFAULT_PATHS alinhados aos runtimes reais.
- Critérios de aceite: testes verdes, CLI funcional, docs em inglês britânico
  (exceto este handoff, que fica em pt-BR), sem dependências de terceiros.

## Contexto
- Nasceu de análise do projeto `Einsia/agent-git` (hub central, login, daemon RC).
  Decidiu-se um análogo local-first: sem servidor, sem daemon, sem conta.
- Stack escolhida pelo usuário: **Python 3.12 stdlib**; nome do projeto:
  **ai-session-vault** em `/mnt/dados/projects/ai-session-vault`.
- Convenção nova registrada em `USER-PREFERENCES.md` (global) e `AGENTS.md`
  (projeto): **todo conteúdo do projeto em inglês britânico, exceto AI_HANDOFF.md**.

## Decisões e premissas
- Formato: JSONL de entrada tolerante (runtimes diferentes têm shapes diferentes);
  linhas malformadas são ignoradas, nunca fatais.
- Vault = diretório com `vault.json` + `.git/` + `sessions/<runtime>/<id>.jsonl`
  + sidecar meta. Cada commit é um commit git normal (ferramentas git funcionam).
- Idempotência por conteúdo (sha256): `add` de mesmo conteúdo não duplica.
- Redação reversível: `[REDACTED:<sha256:12>]` deterministic; dicionário
  secret→placeholder persistível em arquivo 0600 (RedactionDict).
- Premissa validada (ainda não corrigida) — ver CONFIG para detalhes:
  - **claude**: glob atual `~/.claude/projects/*/agent-logs/*.jsonl` PEGA 0 arquivos. Real:
    `~/.claude/projects/<proj>/*.jsonl` na RAIZ do diretório do projeto (85 arquivos; ex
    1dbb8ce4-truncado...). `agent-logs/` contém apenas `.md` (logs de agentes).
  - **claude**: `derive_session_id` truncou o UUID embutido para 24 chars
    (`1dbb8ce4-0e5d-4c5e-a017-` → perdeu 12 chars; pode colidir entre projetos).
    `_first_embedded_id` achou o `sessionId` top-level corretamente, mas o cap de 24
    trunca o UUID de 36.
  - **codex**: glob atual `~/.codex/sessions/*.jsonl` PEGA 0. Real: estrutura
    `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl` (24 arquivos existem).
    Registros codex usam `type:"session_meta"` com `payload.session_id` (ANINHADO em
    `payload`), que `_first_embedded_id` NÃO enxerga → fallback pro stem
    (`rollout-2026-09-06T10-48-...` truncado).
  - **opencode**: NOVO storage (v1) NÃO usa mais JSONL por sessão. Existe
    `~/.local/share/opencode/storage/session_diff/*.json` (vazios `[]`) e o histórico
    em SQLite `opencode.db` (~1GB). Glob `~/.local/share/opencode/storage/session/*.jsonl`
    PEGA 0. Runtime opencode precisa de adaptador (exportar do .db) ou remoção do
    DEFAULT_PATHS até ter suporte real.
  - Ver formato real: claude records `{"type":..., "sessionId":...}`; codex records
    `{"timestamp", "type", "payload"}`.

## Arquivos e componentes
- `src/ai_session_vault/session.py` — parsing JSONL, sha256, turn count, session id.
- `src/ai_session_vault/vault.py` — Vault: init/add/commit/log/status/export_session.
- `src/ai_session_vault/config.py` — VaultConfig + DEFAULT_PATHS + RuntimeRegistry.
- `src/ai_session_vault/transcript.py` — render JSONL → texto legível.
- `src/ai_session_vault/search.py` — busca textual pura (offsets).
- `src/ai_session_vault/redact.py` — low-entropy filter + Redactor + RedactionDict.
- `src/ai_session_vault/cli.py` — argparse dispatcher (8 subcomandos).
- `tests/` — 45 testes (unittest stdlib).
- `scripts/setup.sh`, `scripts/test.sh` — venv + suíte.
- `docs/01_usage.md`, `README.md`, `AGENTS.md`, `pyproject.toml`.

## Alterações realizadas
- Criação do repositório + bootstrap em `main` (`f7e965b`).
- Implementação completa no commit `d228176` (branch `feat/initial-impl`).
- `USER-PREFERENCES.md` global: seção "Idioma dos artefatos de código".

## Validações
- **PR #6 `7d77a12` (feat/opencode-runtime) — validado com evidência fresca por Igor (2026-09-27):**
  - `./scripts/test.sh` → **79 OK** (74→79, +5 testes unitários em `tests/test_opencode.py`).
  - Extração incremental de 41 sessões de `~/.local/share/opencode/opencode.db` em apenas ~26ms após extração inicial.
  - Sincronização e commit reais no vault `~/.ai-session-vault`:
    - `asv sync --runtime codex` -> 30 sessões adicionadas.
    - `asv sync --runtime claude` -> 97 sessões adicionadas.
    - `asv sync --runtime opencode` -> 41 sessões adicionadas.
    - Total de **211 sessões** ativas e saudáveis (`asv status`).
  - `asv find "posts do X.com"` encontrou 5 matches em sessão real do OpenCode instantaneamente.
  - `asv show` renderizou transcrição legível de sessão do OpenCode com turnos de usuário, pensamento e assistente.
- **PR #5 `b00f7ac` (feat/repack-sync-antigravity) — validado com evidência fresca por Igor/Rafael (2026-09-27):**
  - `./scripts/test.sh` (ou `PYTHONPATH=src python3 -m unittest discover -s tests`) → **74 OK** (57→74, +17 testes cobrindo repack, thresholds, sync, streaming find e runtime Antigravity).
  - Execução e verificação real de `asv sync --runtime antigravity` em `~/.ai-session-vault`:
    - Discovered 48 sessions de `~/.gemini/antigravity/brain/`.
    - Added 48 sessions com turn_count e IDs corretos (UUID extraído de `brain/<uuid>`).
    - Commit realizado sem erro (`d95409c1`).
  - `asv status` no vault real: `49 sessions, dirty: no, storage: 105 loose objects [healthy]`.
  - `asv find "scalarup"` via streaming: 1321 matches na sessão atual (`ea28cd4a-...`) e 15 matches em outra sessão Antigravity, com consumo constante de memória.
  - Script transversal `/mnt/dados/projects/scripts/asv` e symlink `~/.local/bin/asv` testados com sucesso a partir de qualquer diretório.
- **PR #3 `df2bc03` (4fd07ff na branch) — validado com evidência fresca por Igor (2026-09-22 ~22:5x):**
  - `PYTHONPATH=src python -m unittest discover -s tests` → **57 OK** (56→57, +1 com PR #3).
  - stdout de teste SEM paths reais: discover `--runtime codex` + tmp dir com stdout capturado (`assertIn` codex e path tmp); config get/set capturam stdout; echo restante é só padrões literais / tmp / version.
  - README:21 `GLOB` confirmado. Diff vistoriado (README + tests/test_cli.py), teste extra `test_config_get_prints_the_stored_pattern`.
  - Nits do PR #2 (README `GLOB`, stdout de teste) **AMBOS fechados**.
- **PR #2 `ea93bf7` (05b7cc7 na branch) — validado com evidência fresca por Igor (2026-09-22 22:30):**
  - `PYTHONPATH=src python -m unittest discover -s tests` → **56 OK** (45→56, +11 com PR #2).
  - claude glob `~/.claude/projects/*/*.jsonl` → **85** arquivos reais; codex glob `~/.codex/sessions/**/*.jsonl` (recursive) → **30** rollouts reais (= `find`).
  - `_first_embedded_id`: claude `sessionId` top-level ✓; codex `payload.session_id` (via `NESTED_ID_CONTAINERS`) ✓ — ambos nos respectivos arquivos reais.
  - `derive_session_id` cap `MAX_SESSION_ID=64` → UUID 36 intacto ✓ (claude 2c37554d-…, codex 01a0761e-…).
  - `turn_count` conta `response_item` com `role` em `payload` ✓ (rollout real: 7 = contagem manual).
  - Repro temp vault (/tmp/asv-pr2-repro): init → config set paths.codex → discover --runtime codex (30) → add codex real → sessão `01a0761e-8f99-7442-8b07-12fcd5f07e1c` = payload.session_id (não o stem `rollout-…`).
  - UX: config get/set paths.claude persiste em vault.json e relê; discover --json JSON válido (count 115 = 85+30), entries runtime+path.
  - Docs cobrem discover/config e paths corrigidos; inglês britânico sem hits US em src/docs/tests/README.
- `./scripts/test.sh` → 45 OK (2026-09-22, pós-fixos `23efa3f` e pós-merge `af54174`).
- `python -m compileall -q src` → OK.
- Smoke test real de CLI em `/tmp/asv-demo` (init, add, commit, log, status,
  show, find, secrets scan/redact, add idempotente, 2ª versão commitada) e
  re-produzido pelo Igor em vault temporário (add de dentro do vault sem
  `--vault`, guarda GitError rc=1 sem traceback, dict 0600 reversível).
- Binário `asv` instalado na venv do projeto rodado → OK.
- Validação de `DEFAULT_PATHS` contra runtimes reais (2026-09-22 22:10): claude
  e codex exercitados via `asv add` real (sha256/idempotência OK).

## Pendências e riscos
- ~~PR #1 em "request changes" (Igor)~~ **RESOLVIDO 2026-09-22**: corrigido no commit `23efa3f`, aprovado e mergeado (`af54174`).
- ~~CORRIGIR DEFAULT_PATHS + extração de IDs~~ **RESOLVIDO 2026-09-22**: PR #2 `ea93bf7` — claude `~/.claude/projects/*/*.jsonl`; codex `~/.codex/sessions/**/*.jsonl` + `payload.session_id`; opencode removido do padrão (v1 sem JSONL por sessão); cap 64. Nits registrados ("Validações") foram tratados no PR #3 `df2bc03` (README `GLOB` + stdout capturado nos testes).
- ~~Implementar ADR-001 e repack de storage~~ **RESOLVIDO 2026-09-27**: PR #5 `b00f7ac` com auto-repack no commit, status de saúde e `asv sync` on-demand (zero cron).
- ~~`find` lê o snapshot completo em memória por busca~~ **RESOLVIDO 2026-09-27**: streaming linha-a-linha no PR #5 (`search_file`).
- ~~Suporte a OpenCode SQLite storage~~ **RESOLVIDO 2026-09-27**: PR #6 `7d77a12` com adaptador incremental `opencode.py`.
- Sem gestão de `--onto`/linhagem/share (fora de escopo deste MVP).

## Próximos passos
1. ~~PR #1~~ ✅ mergeado. ~~PR #2 (DEFAULT_PATHS/IDs)~~ ✅ mergeado `ea93bf7`. ~~PR #3 (nits do PR #2)~~ ✅ mergeado `df2bc03`.
2. ~~PR #5 (ADR-001 Repack, asv sync, Antigravity runtime, streaming search)~~ ✅ mergeado `b00f7ac`.
3. ~~PR #6 (Adaptador SQLite do OpenCode e DEFAULT_PATHS)~~ ✅ mergeado `7d77a12`.
4. `main` local = `origin/main` = `7d77a12` (FF). Todos os 4 runtimes em produção no vault local (`~/.ai-session-vault`).
5. Opcional futuro: empacotamento PyPI (`build`, `twine`) para distribuição global pública como candidato P0 do portfólio.

## Como retomar
- CWD: `/mnt/dados/projects/ai-session-vault`. Estado da implementação está na
  branch `main` (commit `7d77a12`), com `src/`, `tests/`, `docs/`, `scripts/`.
- CLI global pronto para uso: `asv sync`, `asv status`, `asv find <termo>`.
- Rodar suíte: `source .venv/bin/activate && ./scripts/test.sh` (ou
  `PYTHONPATH=src python3 -m unittest discover -s tests`).
- Ler AGENTS.md (projeto) antes de editar; doc em 01_usage.md e ADR-001-session-storage.md.
- Atenção: convenção de idioma — conteúdo do projeto em inglês britânico,
  exceto este handoff.