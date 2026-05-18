#!/bin/bash
set -e

echo "HEAD branch: $(git rev-parse --abbrev-ref HEAD)"

echo "Fetching origin..."
git fetch origin --prune || true

echo "\nBranches (local + remote):"
git branch -a || true

echo "\nRemote show origin:"
git remote show origin || true

FEATURE_REF=origin/feature/discovery-election-2026-05-18
MAIN_REF=origin/main

echo "\nCheck if remote feature branch exists: $FEATURE_REF"
if git show-ref --verify --quiet refs/remotes/feature/discovery-election-2026-05-18; then
  echo "Found local remote ref refs/remotes/feature/discovery-election-2026-05-18"
fi
if git show-ref --verify --quiet "refs/remotes/origin/feature/discovery-election-2026-05-18"; then
  echo "Remote branch exists: $FEATURE_REF"
else
  echo "Remote branch $FEATURE_REF not found"
fi

echo "\nRecent commits on remote feature branch (if present):"
git --no-pager log --oneline --decorate --graph "${FEATURE_REF}" -n 20 || true

echo "\nCommits on feature not in main:"
git --no-pager log --oneline "${MAIN_REF}..${FEATURE_REF}" -n 50 || true

echo "\nFiles changed vs main (name and status):"
# use three dots to get diff since merge base
git --no-pager diff --name-status "${MAIN_REF}...${FEATURE_REF}" || true

echo "\nFiles added that look like compiled/temp/binaries:" 
git --no-pager diff --name-only "${MAIN_REF}...${FEATURE_REF}" | egrep -i '(__pycache__|\.pyc|\.pyo|\.exe|\.dll|\.class|\.jar|\.log|node_modules|\.DS_Store|\.sqlite)' || true

echo "\nLocal git status (porcelain):"
git status --porcelain || true

echo "\nLast 10 commits (local):"
git --no-pager log --oneline -n 10 || true
