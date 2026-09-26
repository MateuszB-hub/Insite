#!/usr/bin/env bash
# Tag a commit on main as the next release: vYYYY.MM.DD-N (UTC date).
#
#   scripts/release_tag.sh [COMMIT]     (default: HEAD)
#
# Run by the `release:tag` CI job after every merge to main; the tag it
# pushes starts the release pipeline (deploy to staging, then a manual
# "deploy to live" button). Safe to re-run: a commit that already carries a
# v* tag is left alone.
#
# The push goes to the plain HTTPS remote, so it authenticates with the Mac's
# stored GitLab token (Keychain), not the CI job token -- job tokens cannot
# create tags.
set -euo pipefail

commit="$(git rev-parse "${1:-HEAD}")"
remote="https://gitlab.com/${CI_PROJECT_PATH:-insite-group/insite}.git"

git fetch -q --tags "$remote"

existing="$(git tag --points-at "$commit" --list 'v*' | head -n 1)"
if [ -n "$existing" ]; then
  echo "already released as $existing"
  exit 0
fi

today="$(date -u +%Y.%m.%d)"
n=1
while git rev-parse -q --verify "refs/tags/v$today-$n" >/dev/null; do
  n=$((n + 1))
done
tag="v$today-$n"

subject="$(git log -1 --format=%s "$commit")"
# Tags are mirrored to the public GitHub repo, so the tagger is always the
# public noreply identity the commits use -- never the Mac's global git
# identity or GitLab's user email, which may be a personal address.
git -c user.name="${RELEASE_GIT_NAME:-MateuszB-hub}" \
    -c user.email="${RELEASE_GIT_EMAIL:-65938049+MateuszB-hub@users.noreply.github.com}" \
    tag -a "$tag" -m "Release $tag: $subject" "$commit"
git push -q "$remote" "refs/tags/$tag"
echo "released $tag at ${commit:0:8}"
