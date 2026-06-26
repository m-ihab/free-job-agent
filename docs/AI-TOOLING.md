# AI Tooling: GitNexus, Graphify, and Obsidian

This project uses three local, free tools. They solve **two different problems** — don't conflate them.

| Tool | Indexes | Helps | Output | In git? |
|------|---------|-------|--------|---------|
| **GitNexus** | the codebase (symbols, call graph, execution flows) | an **AI editing the code** ("what breaks if I change `safe_get`?") | `.gitnexus/` (~73 MB DB) | **No** — regenerable |
| **Graphify** | the codebase (community/graph) | scoped code Q&A without grepping | `graphify-out/` (~13 MB) | **No** — regenerable |
| **Obsidian** | your **job search** (one note per job/company/skill) | **you**, tracking and seeing the search as a graph | `second-brain/` (personal) | **No** — private data |

All three outputs are gitignored: the index DBs are large and regenerable; the vault holds personal job data and must stay local (project constraint: *keep all data local*). What **is** committed is the code and instructions that make them work.

---

## GitNexus + Graphify — code intelligence for the AI

These exist so an assistant working on the **code** can reason about impact and structure instead of guessing. Usage is documented in `AGENTS.md` (GitNexus) and `CLAUDE.md` (Graphify).

Keep the indexes fresh after code changes:

```bash
node .gitnexus/run.cjs analyze     # or: npx gitnexus analyze   -> rebuilds .gitnexus/
graphify update .                  # -> rebuilds graphify-out/ (AST-only, no API cost)
```

They are **not** about your job data — they map the program.

---

## Product-truth vs generated-truth

GitNexus and Graphify help agents understand code impact, execution flows, and relationships. They are not the canonical product policy.

When generated graph output disagrees with source docs, use this order:

1. `CLAUDE.md`
2. `FULL_AUTO_CONTRACT.md`
3. `README.md`
4. `architecture.md`
5. `PLAN.md` / `SESSION-HISTORY.md`
6. Regenerated Graphify/GitNexus output

After changing apply behavior, dashboard routes, pipeline status, database schema, or UI workflows, regenerate both indexes:

```bash
node .gitnexus/run.cjs analyze
graphify update .
```

Do not hand-edit `graph.json`. Treat `GRAPH_REPORT.md` as a generated navigation snapshot, not a roadmap.

---

## Obsidian — make the job search a graph

The vault only becomes useful when notes are **linked**. A pile of 150 unconnected notes produces a graph of disconnected dots. The exporter fixes that by turning your job database into linked notes:

```bash
job-agent obsidian-sync                 # writes ./second-brain (or --vault <dir>)
```

It generates, alongside any manual notes:

```text
second-brain/
  Dashboard.md                 # map-of-content: jobs grouped by status, top fits, Dataview view
  jobs/<title>-<company>.md    # one note per job, frontmatter + [[company]] + [[skill]] links
  companies/<company>.md       # hub note backlinking every job at that company
  skills/<skill>.md            # hub note backlinking every job needing that skill
```

Because each job note wikilinks `[[company]]` and each skill, Obsidian's **graph view** surfaces companies and skills as **hub nodes** — you can see which companies you're chasing, which skills recur, and what's `NEEDS_MANUAL` vs `PACKET_READY`.

### Why it's useful

- **Graph view**: clusters around companies/skills; isolated nodes = jobs you haven't enriched.
- **Dashboard.md**: a single entry point grouped by status and fit score.
- **Backlinks**: open a company note to see every role you've found there.
- **Dataview** (optional plugin): `Dashboard.md` includes a live table of all jobs.

### Workflow

1. Find jobs: `job-agent hunt ...` or `job-agent multi-search --save`.
2. Sync: `job-agent obsidian-sync`.
3. Open `second-brain/` in Obsidian → open **Dashboard.md** → toggle the **graph view**.
4. Re-run `obsidian-sync` anytime; notes are overwritten in place with stable filenames.

A manual job-note template lives at `second-brain/_templates/job.md` for notes you write by hand (kept local). Configure a different vault location via `obsidian_vault_dir` in `config.json` or the `--vault` flag.
