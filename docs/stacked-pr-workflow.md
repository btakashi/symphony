# Stacked PR Workflow

Use stacked branches when Symphony Python work has dependent slices that should be reviewed or
merged independently. Each branch should contain one coherent change and should target the branch it
depends on, not always `main`.

## Branch Shape

Name branches for the issue or slice they implement:

```text
python-pre-commit-hooks
python-run-ledger
python-fake-orchestrator
python-claude-headless-runner
```

For a stack, keep the dependency order explicit:

```text
main
└── python-pre-commit-hooks
    └── python-fake-orchestrator
        └── python-claude-headless-runner
```

The PR target should match the immediate parent branch:

| Branch | PR base |
| --- | --- |
| `python-pre-commit-hooks` | `main` |
| `python-fake-orchestrator` | `python-pre-commit-hooks` |
| `python-claude-headless-runner` | `python-fake-orchestrator` |

When the base branch lands, retarget or restack the child PRs onto the next live parent.

## Preferred Graphite Flow

Use Graphite CLI when it is installed, authenticated, and initialized for the repo. Graphite tracks
the stack locally and can create or update GitHub PRs for each branch.

Typical flow:

```bash
gt sync
# edit files for one issue/slice
gt add <paths>
gt create python-fake-orchestrator -m "feat(python): add fake orchestrator"
gt submit
```

For follow-up changes on the current branch:

```bash
gt add <paths>
gt modify --commit --message "Address review feedback"
gt submit
```

To change stack order or move a branch to a different parent, prefer `gt move` so Graphite restacks
children consistently.

## Plain Git And GitHub Fallback

When Graphite is unavailable, use ordinary Git branches and GitHub PR bases.

Create the first branch from `main`:

```bash
git fetch origin
git switch -c python-pre-commit-hooks origin/main
# edit, test, commit
git push -u origin python-pre-commit-hooks
gh pr create --base main --head python-pre-commit-hooks
```

Create a child branch from its parent branch:

```bash
git switch python-pre-commit-hooks
git switch -c python-fake-orchestrator
# edit, test, commit
git push -u origin python-fake-orchestrator
gh pr create --base python-pre-commit-hooks --head python-fake-orchestrator
```

If the parent branch changes, rebase the child branch and force-push with lease:

```bash
git fetch origin
git switch python-fake-orchestrator
git rebase origin/python-pre-commit-hooks
git push --force-with-lease
```

When a parent PR is merged, retarget the next child PR to the merged parent of the stack, usually
`main`, then rebase and push.

## Fork Targets

If you do not have push access to the upstream repository, push the same branch names to your fork
and open PRs against the upstream repository.

For the first PR in a stack:

```bash
git push -u fork python-pre-commit-hooks
gh pr create --repo upstream-owner/symphony --base main --head your-user:python-pre-commit-hooks
```

For child PRs, keep the upstream base branch set to the parent branch name:

```bash
git push -u fork python-fake-orchestrator
gh pr create \
  --repo upstream-owner/symphony \
  --base python-pre-commit-hooks \
  --head your-user:python-fake-orchestrator
```

This requires the parent branch to exist in the upstream repository. If only your fork contains the
parent branch, either ask a maintainer to push the parent branch upstream, keep the stack local until
the parent lands, or collapse the dependent work into a single PR.

## Review And Landing Rules

- Keep each PR focused on one Beads issue or one obvious implementation slice.
- Include the parent PR link in each child PR description.
- Run `cd python && uv run poe check` before publishing each branch.
- Do not merge a child before its parent unless the child has been retargeted and revalidated.
- Prefer `--force-with-lease` over plain force-push when restacking manually.
- After landing a parent branch, update child branches promptly so GitHub diffs stay reviewable.
