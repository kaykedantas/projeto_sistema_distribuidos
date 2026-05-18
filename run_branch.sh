#!/bin/bash
set -euo pipefail
BRANCH="feature/discovery-election-2026-05-18"
CURRENT=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $CURRENT"

# Create or checkout branch
if [ "$CURRENT" != "$BRANCH" ]; then
  if git show-ref --verify --quiet refs/heads/$BRANCH; then
    echo "Branch $BRANCH exists locally — checking out"
    git checkout $BRANCH
  else
    echo "Creating branch $BRANCH from $CURRENT"
    git checkout -b $BRANCH
  fi
else
  echo "Already on $BRANCH"
fi

# Push branch
echo "Pushing branch $BRANCH to origin..."
if git push -u origin $BRANCH; then
  echo "PUSH_OK"
else
  echo "PUSH_FAILED"
fi

# Attempt to create PR with gh
PR_OUTPUT=""
if command -v gh >/dev/null 2>&1; then
  echo "gh found: checking auth..."
  if gh auth status >/dev/null 2>&1; then
    echo "gh authenticated — creating PR..."
    PR_OUTPUT=$(gh pr create --base main --head $BRANCH --title "feat: descoberta e eleição (spec+tests)" --body $'Resumo:\n- Implementa descoberta UDP, eleição determinística e handshake TCP.\n\nTest Plan:\n- pytest (4 passed local)\n\nArquivos alterados:\n- src/discovery.py, src/election.py, src/handshake.py\n- tests/*') || true
    echo "PR_OUTPUT: $PR_OUTPUT"
  else
    echo "GH_NOT_AUTH"
  fi
else
  echo "GH_MISSING"
fi

# Show recent commits and diff
echo "--- recent commits on this branch ---"
git --no-pager log --oneline -n 8

echo "--- files changed relative to origin/main (if available) ---"
# attempt to fetch origin/main reference
if git show-ref --verify --quiet refs/remotes/origin/main; then
  git --no-pager diff --name-only origin/main..HEAD || true
else
  echo "origin/main unknown (remote may not have branch yet)"
fi

# Print remote URL of created PR if any
if [ -n "$PR_OUTPUT" ]; then
  echo "PR_CREATED_OUTPUT:\n$PR_OUTPUT"
fi
