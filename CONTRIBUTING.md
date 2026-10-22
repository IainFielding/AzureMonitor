# Contributing

Thanks for taking the time to contribute. The workbook is generated, so changes go into the
generator script rather than the JSON.

## Making a change

Edit the workbook's script in [src/](src/) (the shared helpers are in
[src/build_workbook.py](src/build_workbook.py)), regenerate, and commit the script and the generated JSON. The
Grafana dashboards are generated from the platform health workbook's definition. Run them all:

```sh
python src/build_workbook.py
python src/build_firewall_troubleshoot.py
python src/build_backup.py
python src/build_dns_troubleshoot.py
python src/build_changes.py
python src/build_policy_denials.py
python src/build_avd_user.py
python src/build_log_cost.py
python src/build_routing.py
python src/build_avs.py
python src/build_sentinel.py
python src/build_privileged_access.py
python src/build_expiry.py
python src/build_availability.py
python src/build_grafana.py
```

## Before opening a pull request

- Regenerating the workbook and the Grafana dashboards leaves no uncommitted changes (CI checks this).
- The change has been imported and checked in the Azure portal — nothing in CI runs the workbook.

Keep pull requests small and focused; unrelated changes bundled together are much slower
to review.

## Commit messages

Write a short imperative subject line describing the change, and use the body for the
reasoning if it isn't obvious from the diff. Every commit needs a sign-off, and no commit
should carry AI tool attribution — both are explained below.

### Sign your work — the Developer Certificate of Origin

Every commit must be signed off. Sign-off is a single trailer at the end of the commit
message:

```
Signed-off-by: Your Name <your.email@example.com>
```

`git commit -s` adds it for you, using your configured `user.name` and `user.email`.

Adding that line certifies that you wrote the change, or otherwise have the right to
submit it under this project's licence. The full text of what you are certifying is the
Developer Certificate of Origin 1.1, reproduced verbatim in [DCO](DCO) at the root of this
repository.

This is **not** a contributor licence agreement. There is no paperwork to sign and no
rights are assigned to anyone; you are simply asserting, per commit, that the code was
yours to give.

This repository ships a hook that adds the trailer for you, including on commits made from
an editor's source-control panel, which never pass `-s`:

```sh
git config core.hooksPath .githooks
```

`git config format.signOff true` does **not** do this: it is honoured only by
`git format-patch` and `git send-email`.

If you forget, CI will tell you. To fix it:

```sh
git commit --amend -s --no-edit       # the most recent commit
git rebase --signoff origin/main      # every commit on your branch
```

Then force-push the branch.

### AI-assisted contributions

AI coding assistants are permitted. You remain fully responsible for the correctness,
licensing, and style compliance of anything you submit, and you must be able to explain
your change on request.

Please do **not** include AI tool attribution in commit messages. Remove trailers such as
`Co-Authored-By: Claude ...`, `Co-authored-by: Copilot ...`, "Generated with ..." footers,
and similar tool sign-offs before opening a pull request.

The same `core.hooksPath` setting above also turns on a hook that catches this before you
commit, and `.github/workflows/no-ai-attribution.yml` checks every pull request in CI.
