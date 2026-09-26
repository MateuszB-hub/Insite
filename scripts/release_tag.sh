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
# The tag is made and pushed from a fresh bare clone in a temp folder, not
# from the CI checkout: GitLab Runner configures its checkout to sign in with
# the job token, which can read the repository but never push ("You are not
# allowed to push code to this project", 403). Outside that checkout, git
# uses this machine's own credentials (the Keychain token), which can.
set -euo pipefail

commit="$(git rev-parse "${1:-HEAD}")"
remote="https://gitlab.com/${CI_PROJECT_PATH:-insite-group/insite}.git"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# Blobs aren't needed to tag a commit, so this stays small and quick.
git clone -q --bare --filter=blob:none "$remote" "$work/repo"
cd "$work/repo"
git cat-file -e "$commit^{commit}" 2>/dev/null \
  || { echo "commit ${commit:0:8} is not on $remote"; exit 1; }

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
git push -q origin "refs/tags/$tag"
echo "released $tag at ${commit:0:8}"
