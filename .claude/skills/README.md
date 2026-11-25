# Vendored Claude Code skills

Copied from two plugins on 2026-11-25. Each skill folder is unmodified.

| Skills | Source | Commit | License |
|---|---|---|---|
| `gf*`, `tb-best-practices` (27) | [codejunkie99/Gateflow-Plugin](https://github.com/codejunkie99/Gateflow-Plugin) `plugins/gateflow/skills/` | `bf7e94c` | BSL-1.1, see `LICENSE-gateflow` |
| the other 14 | [LilithSemi/claude-for-hardware](https://github.com/LilithSemi/claude-for-hardware) `skills/` | `a4c4a00` | MIT, see `LICENSE-claude-for-hardware` |

Notes:
- Many `gf*` skills hand work to Gateflow agents (`sv-codegen`, `sv-testbench`, ...)
  that ship only with the Gateflow plugin. `gf-ip` and `gf-pinmap` also read IP
  blocks and board files through `${CLAUDE_PLUGIN_ROOT}`. Those parts work only
  with the plugin installed.
- RTL style is set by `docs/spec.md` §14 (SystemVerilog-2017). Where a skill
  suggests another style, the spec wins.
