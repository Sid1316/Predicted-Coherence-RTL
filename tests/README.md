# Upstream test suites

Both suites are git submodules (exec.md task M0.4). After cloning this repository, fetch them with:

```bash
git submodule update --init --recursive
```

They are pinned so the test names in docs/spec.md §15 refer to a fixed version:

| Submodule | Pinned version | Why |
|---|---|---|
| `tests/riscv-tests` | `1b3f8bd` (master, 2026-11-24) | Latest at setup time; `isa/rv32ui/` names match spec.md §15 |
| `tests/riscv-arch-test` | tag `3.10.0` (`fc32e41`, 2024-11-05) | Last release with the RISCOF layout (`riscv-test-suite/rv32i_m/I/src/*-01.S`) that the plan uses. Newer `main` has moved to a different framework and layout. |

To move a pin, check out the new commit inside the submodule, then `git add tests/<name>` in this repository and update the table.

`tests/riscof/` holds the RISCOF configuration and the DUT plugin (M5.3).
