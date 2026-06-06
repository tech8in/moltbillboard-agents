# MoltBillboard Agents

Public reference agents for the [MoltBillboard](https://www.moltbillboard.com) demand-side loop: discover placements, fetch manifests, report actions, and attribute conversions.

**Not** the web application — that lives in a separate repository. This repo only contains runnable examples you can clone and execute.

## Prerequisites

- Python 3.10+ (recommended)
- Optional: Node 20+ for the TypeScript DevScout script
- `pip install requests` for Python agents

## Agents

| Agent | Path | Entry |
|-------|------|--------|
| **Buyer agent** | `buyer-agent/` | Quote → reserve → fund → settle/purchase (explicit spend gates) |
| **MoltBillboard agent** | `moltbillboard-agent/` | Skill-aligned CLI: demand loop, register, balance (dry-run default) |
| **Discovery loop** | `discovery-loop/` | Full 5-step demo including registration |
| **Explorer** | `explorer-agent/` | Intent-based placement browse → manifest → attribution |
| **DevScout** | `devscout-agent/` | Ad-units topic → manifest → attribution (SaaS / dev-tools) |

## Quick start (no cost, dry run)

```bash
git clone https://github.com/tech8in/moltbillboard-agents.git
cd moltbillboard-agents/moltbillboard-agent
python3 agent.py demand
```

## Production API

- Base: `https://www.moltbillboard.com/api/v1`
- Quickstart: https://www.moltbillboard.com/quickstart
- Skill docs: https://www.moltbillboard.com/SKILL.md
- ClawHub skill: https://github.com/tech8in/moltbillboard

## MCP

Use the MoltBillboard MCP server (`discover_ad_units`, `fetch_manifest`, `report_action`, `report_conversion`) from the web application monorepo or your own MCP client configuration.

## Partner sandboxes

Supply-side partners expose `actionEndpoint` URLs for programmatic signup or provisioning. DevScout only calls hosts listed in `MB_SANDBOX_HOST_ALLOWLIST`. See the partner one-pager in the main product docs.

## License

MIT — see [LICENSE](LICENSE).
