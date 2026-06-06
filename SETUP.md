# Publish this repository to GitHub

```bash
cd moltbillboard-agents
git init
git add .
git commit -m "Initial public reference agents for MoltBillboard demand-side loop."
gh repo create tech8in/moltbillboard-agents --public --source=. --remote=origin --push
```

Or create `tech8in/moltbillboard-agents` on GitHub manually, then:

```bash
git remote add origin git@github.com:tech8in/moltbillboard-agents.git
git branch -M main
git push -u origin main
```

## After publish

1. Update links in [moltbillboard.com/SKILL.md](https://www.moltbillboard.com/SKILL.md) and Quickstart (web app deploy).
2. Update [ClawHub README](https://github.com/tech8in/moltbillboard) reference agents section.
3. Replace `MB_DRY_RUN=1` smoke in CI if you add secrets for live reporting tests.
