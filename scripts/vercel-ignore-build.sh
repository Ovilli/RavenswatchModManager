#!/bin/sh
# Vercel "Ignored Build Step" for the www, docs and api projects.
#
#   sh scripts/vercel-ignore-build.sh www|docs|api
#
# Exit 0 = skip this deploy, anything else = build. Skips only when every file
# changed since the project's last successful deploy lies in a path that site
# never reads. Every push used to redeploy both sites, and a new deployment
# starts with an empty ISR cache, so API-only or Python-only commits made the
# website re-render every page from scratch (Fluid Active CPU). An API deploy
# also replaces every warm instance, so each push cost a round of cold starts
# (~730 ms CPU each before the lazy-import work) for nothing.
#
# Fails toward building: a missing or unfetched base commit (Vercel clones
# shallow) makes git diff exit 128, which builds. When adding a new input to a
# site (e.g. www starts reading data/), remove that path from its list here.
set -u

common=':(top,exclude)apps/desktop :(top,exclude)tests
:(top,exclude)data :(top,exclude)docs :(top,exclude)scripts :(top,exclude)tools
:(top,exclude)services :(top,exclude).github :(top,exclude).claude'

case "${1:-}" in
  # www reads apps/www + packages/* (+ root config, lockfile).
  www) excludes="$common :(top,exclude)apps/api :(top,exclude)apps/docs :(top,exclude)src" ;;
  # docs reads apps/docs + src/rsmm (packed into /editor/rsmm.bundle).
  docs) excludes="$common :(top,exclude)apps/api :(top,exclude)apps/www :(top,exclude)packages :(top,exclude)src/loader" ;;
  # api reads apps/api + packages/* (db schema, shared schemas).
  api) excludes="$common :(top,exclude)apps/www :(top,exclude)apps/docs :(top,exclude)src" ;;
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
git diff --quiet "$base" "$head" -- ':/' $excludes
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
