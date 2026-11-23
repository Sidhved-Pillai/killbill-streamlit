#!/bin/zsh

# Safely fast-forward the local KillBill checkout when VS Code opens it.
# Local work always wins: any branch change or uncommitted file causes a skip.

set -u

repository_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "KillBill sync skipped: this folder is not a Git repository."
    exit 0
}
cd "$repository_root" || exit 0

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
    echo "KillBill sync skipped: current branch is '$current_branch', not 'main'."
    exit 0
fi

if ! git diff --quiet || ! git diff --cached --quiet || \
   [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    echo "KillBill sync skipped: local changes are present. Commit or stash them first."
    exit 0
fi

echo "Checking GitHub for KillBill updates..."
if ! git fetch --prune origin main; then
    echo "KillBill sync could not reach GitHub. The existing local files were not changed."
    exit 0
fi

behind_count="$(git rev-list --count HEAD..origin/main)"
ahead_count="$(git rev-list --count origin/main..HEAD)"

if (( ahead_count > 0 )); then
    echo "KillBill sync skipped: local main contains commits not present on GitHub."
    exit 0
fi

if (( behind_count == 0 )); then
    echo "KillBill is already up to date."
    exit 0
fi

if git merge --ff-only origin/main; then
    echo "KillBill updated successfully from GitHub main."
else
    echo "KillBill sync stopped safely because a fast-forward was not possible."
fi

