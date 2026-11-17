#!/bin/sh
# Vercel "Ignored Build Step" for the www, docs and api projects.
#
#   sh scripts/vercel-ignore-build.sh www|docs|api
#
# Exit 0 = skip this deploy, anything else = build. Skips only when every file
# changed since the project's last successful deploy lies outside the paths
# that site reads. Every push used to redeploy both sites, and a new deployment
# starts with an empty ISR cache, so API-only or Python-only commits made the
# website re-render every page from scratch (Fluid Active CPU). An API deploy
# also replaces every warm instance, so each push cost a round of cold starts
# (~730 ms CPU each before the lazy-import work) for nothing.
#
# Since 2026-11-12 this decides deploys from GitHub Actions
# (.github/workflows/deploy.yml), which runs it BEFORE contacting Vercel. Run as
# Vercel's Ignored Build Step, a skip still CREATED a deployment (started, then
# cancelled), and those count toward the Hobby plan's 100 deployments a day:
# with three projects every push to any branch cost three (76 in one day, 58 of
# them previews). Vercel's own Git deploys are now off (git.deploymentEnabled:
# false in each vercel.json: root, apps/api, apps/docs), so a project with no
# changed input costs nothing. Vercel still runs ignoreCommand for a manual
# redeploy from its dashboard.
#
# Fails toward building: a missing or unfetched base commit (Vercel clones
# shallow) makes git diff exit 128, which builds.
#
# Each site lists the paths it reads; a change anywhere else skips it. A list of
# what to leave out let every new root file (README.md, CLAUDE.md, .gitignore)
# deploy all three. When a site starts reading a new path (e.g. www reads
# data/), add it to that site's list here.
set -u

# What every project's install reads (pnpm install --frozen-lockfile, and the
# upload filter).
install=':(top)package.json :(top)pnpm-lock.yaml :(top)pnpm-workspace.yaml :(top).vercelignore'

case "${1:-}" in
  # www: apps/www + packages/* (api-client, schemas, ui, tsconfig) + the root
  # vercel.json, which is www's project config.
  www) inputs="$install :(top)apps/www :(top)packages :(top)vercel.json" ;;
  # docs: apps/docs + src/rsmm (packed into /editor/rsmm.bundle).
  docs) inputs="$install :(top)apps/docs :(top)src/rsmm" ;;
  # api: apps/api (its vercel.json included) + packages/* (db schema, shared
  # schemas).
  api) inputs="$install :(top)apps/api :(top)packages" ;;
  *) echo "usage: $0 www|docs|api" >&2; exit 1 ;;
esac

base="${VERCEL_GIT_PREVIOUS_SHA:-HEAD^}"
head="${VERCEL_GIT_COMMIT_SHA:-HEAD}"
# Vercel's shallow checkout may not contain the previous successful deployment
# commit. Try the object directly, then deepen the deployment branch in case
# the Git host only allows fetching advertised refs.
if ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
  echo "Previous deployment commit $base is missing; attempting to fetch it."
  git fetch --no-tags --depth=1 origin "$base" >/dev/null 2>&1 || true
  if ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
    branch="${VERCEL_GIT_COMMIT_REF:-}"
    if [ -n "$branch" ] && git check-ref-format "refs/heads/$branch" >/dev/null 2>&1; then
      for depth in 100 500 2000 8000; do
        git fetch --no-tags --deepen="$depth" origin "refs/heads/$branch" >/dev/null 2>&1 || break
        if git cat-file -e "${base}^{commit}" 2>/dev/null; then
          echo "Fetched previous deployment commit by deepening $branch history."
          break
        fi
      done
    fi
  fi
fi
# shellcheck disable=SC2086 # word-splitting the pathspec list is intended
git diff --quiet "$base" "$head" -- $inputs
status=$?
if [ "$status" -eq 0 ]; then
  echo "No $1 inputs changed since $base; skipping build."
  exit 0
elif [ "$status" -eq 1 ]; then
  echo "$1 inputs changed since $base; building."
  exit 1
else
  echo "Could not compare $1 inputs since $base (git diff exit $status); building conservatively."
  # Vercel expects exit 1 to mean "run the build". Preserve the underlying
  # git status in the message, but don't pass git's status (for example 128)
  # through as an ignore-command failure.
  exit 1
fi
