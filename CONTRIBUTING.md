# Branch workflow

Use one short branch for one task. Name the task, not the person:
`feat/stock-reservation` or `fix/invoice-currency`.

| Branch | Purpose | Changes arrive through |
| --- | --- | --- |
| `main` | Source for production releases | A reviewed release PR from `develop`, or a reviewed hotfix PR |
| `develop` | Shared development integration | Reviewed task PRs with passing checks |
| `feat/<task>` or `fix/<task>` | One piece of work | Create from the latest `develop`; merge back into `develop` |

## Start a task

```bash
git fetch origin
git switch develop
git pull --ff-only origin develop
git switch -c feat/short-task-name
```

Commit and push your task branch. Open a PR with `develop` as the base. Ask a
teammate who did not write the change to review it. Wait for the `backend`,
`frontend`, and `postgres-regressions` checks to pass before merging. Delete
the task branch after merge; create a fresh branch for the next task.

If `develop` changes while you work, sync your task branch before the PR:

```bash
git fetch origin
git merge origin/develop
```

Resolve conflicts by understanding both changes and preserving the intended
business behavior. Run the affected tests after resolving them. Tell the team
early if two tasks need the same files. Keep PRs small enough for a teammate to
review. Do not force-push `main`, `develop`, or a branch another person uses.

## Release and hotfix

Release through a PR from `develop` to `main` after checking the combined code
and following the deployment runbook. Before that PR, bring any hotfixes made
on `main` back into `develop` and test the result. For an urgent production
fix, branch from `main`, open a reviewed hotfix PR to `main`, then sync the fix
back into `develop`.

A direct push to `main` changes the release source without the team's review
and merge decision. A push is not itself a deployment; the release process
decides what is deployed.

## Repository settings for an administrator

Protect both `main` and `develop`: require a PR, at least one approval from
someone other than the author, passing `backend`, `frontend`, and
`postgres-regressions` checks, and resolved review conversations. Block force
pushes and branch deletion. Apply these rules to administrators unless an
explicit emergency bypass policy is documented.

GitHub references: [pull request workflow](https://docs.github.com/en/pull-requests/get-started/pull-request-quickstart),
[keeping a branch current](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/keeping-your-pull-request-in-sync-with-the-base-branch),
and [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
