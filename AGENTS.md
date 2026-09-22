# AGENTS.md — ai-session-vault

Projeto local-first de versionamento de sessões de agentes de IA sobre Git.

## Princípios do projeto

- **Local-first**: todo o estado vive localmente (JSONL + sidecars + git). Nada sai da máquina por padrão.
- **Formatos abertos**: JSONL puro + metadados JSON sidecar; git é o mecanismo de versão.
- **Sem lock-in**: migração trivial via `git` ou cópia de arquivos; tipos de sessão registrados em config.
- **Segredos**: filtro de baixa entropia + placeholders reversíveis; nada sensível versionado em texto claro.

## Convenções

- Python 3.12+ stdlib (zero dependências de terceiros em runtime).
- TDD: escrever teste antes da implementação; suíte em `tests/` (unittest).
- Estrutura: `src/ai_session_vault/` pacote; `scripts/` para operações; `docs/` para guias.
- Contrato CLI: subcomandos curtos e `--json` para automação, saída humana para terminal.

## Validações obrigatórias

- `./scripts/test.sh` — roda a suíte completa.
- Ao criar subcomando novo: atualizar `docs/01_usage.md`.

Veja também `/home/afmpjr/AGENTS.md` (diretrizes globais) e `/home/afmpjr/AI_ONBOARDING.md` (protocolo de sessão).