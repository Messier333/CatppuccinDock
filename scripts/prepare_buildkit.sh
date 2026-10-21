#!/bin/sh
# Select a verified, downloadable BuildKit image for setup-buildx-action.
set -eu
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT must point to the workflow output file}"

buildkit_ref='moby/buildkit:v0.34.1@sha256:99368f3e46177c6405b9740e4461d91cee004128daeecca78d4ceac50ec1da5c'
# Google can evict cached images. Fall back to the same digest on Docker Hub.
for registry in mirror.gcr.io docker.io; do
    image="$registry/$buildkit_ref"
    for attempt in 1 2; do
        if timeout 45s docker pull "$image"; then
            printf 'image=%s\n' "$image" >> "$GITHUB_OUTPUT"
            exit 0
        fi
        printf 'BuildKit pull failed (%s, attempt %s/2).\n' "$registry" "$attempt" >&2
        if [ "$attempt" -lt 2 ]; then sleep 2; fi
    done
done
printf 'Cannot download the pinned BuildKit image from either registry.\n' >&2
exit 1
