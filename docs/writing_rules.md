# Writing Rules

## Strict runtime and tooling rules

These rules are mandatory for this repository.

### 1. Bun-only JavaScript execution

Use **Bun** for JavaScript and TypeScript commands.

Allowed examples:

- `bun run <script>`
- `bun test ...`
- `bun tools/file.mjs`
- `bun install`

Disallowed examples:

- `npm ...`
- `node ...`
- `npx ...`
- `yarn ...`
- `pnpm ...`

Notes:

- Do not introduce new `node` or `npm` commands in docs, scripts, CI, tests, or helper tools.
- If a test or script needs JS execution, prefer a Bun script in `package.json` or direct `bun ...` execution.
- Existing legacy `node` references should be migrated to Bun-compatible equivalents when touched.

### 2. Python test rules

- Use `pytest` for Python tests.
- Keep fast tests CI-safe and independent from live ChatGPT when possible.
- Mark live browser tests with `browser_e2e` and keep them opt-in.

### 3. Test pyramid rules

Preferred order:

1. unit / parser tests
2. proxy contract tests
3. fake-daemon protocol tests
4. optional real-browser smoke tests

Do not rely on live ChatGPT for the main CI path.

### 4. Documentation rules

When adding or changing tests, document:

- which source file(s) the test protects
- whether the test is unit, contract, protocol, or browser E2E
- whether the test is fast or opt-in

### 5. CI rules

- fast CI must run without browser secrets
- browser E2E must live in a separate manual/nightly path
- JS tests in CI must run through Bun
