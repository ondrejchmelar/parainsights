#!/bin/sh
# Refuse to publish a report older than the code that renders it.
#
# `public/index.html` is a committed build artifact: building it needs the IGC files, and
# flight tracks stay out of this repository. That is a defensible trade, and it failed in
# a specific way — the renderer changed, nobody rebuilt, and the site sat weeks out of
# date behind a wall of green pipelines, because the `pages` job checked only that the
# file existed. Someone eventually noticed the compass rose was still bottom-left.
#
# This cannot rebuild the page. What it can do is ask whether the commit that last built
# the page *contains* the last change to each thing that renders it. If it does not, the
# two do not match and the pipeline says so instead of publishing the mismatch.
#
# Run it locally before committing a renderer change, and it will tell you what to
# rebuild:
#
#     sh ci/stale.sh
#
# The rebuild is in the "Known gaps" section of CLAUDE.md.
set -eu

PAGE=public/index.html

# Everything whose output ends up inside that file. `airspaces` and
# `parainsights_common` are in the list for the same reason as the viewer: the report
# carries the airspace layer as one of its views and the nav strip as its header, so a
# change to either leaves the published copy a version behind the standalone page. This
# is the list CLAUDE.md's "including when only `airspaces` or `view3d` changed" names.
SOURCES="tracklog_viewer airspaces parainsights_common"

commit_of() {
    # The last commit that touched a path, or nothing. A shallow CI clone may not reach
    # it, and that case is handled below rather than guessed at.
    git log -1 --format=%H -- "$1" 2>/dev/null || true
}

if [ ! -f "$PAGE" ]; then
    echo "stale.sh: no $PAGE — nothing to check" >&2
    exit 0
fi

# Loudly, rather than shrugging. Without git this check answers "no idea" for every path
# and passes — which is indistinguishable from a fresh page, and is precisely the silent
# green pipeline the whole script exists to stop.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "stale.sh: no git history here, so freshness cannot be checked." >&2
    echo "stale.sh: install git, or run this from a clone." >&2
    exit 1
fi

page_commit=$(commit_of "$PAGE")
stale=""
for source in $SOURCES; do
    source_commit=$(commit_of "$source")
    [ -n "$source_commit" ] || continue          # not in a shallow clone's window
    if [ -z "$page_commit" ]; then
        # The source changed inside the window and the page did not. Exactly the state
        # this exists to catch, and the one a shallow clone shows most clearly.
        stale="$stale $source"
        continue
    fi
    # **Ancestry, not timestamps.** Two commits made in the same second compare equal by
    # date, and a rebuild committed a second after the renderer change would sail
    # through — which is not a hypothetical, it is what a scripted "change, then
    # rebuild, then commit" does. Asking whether the page's commit *contains* the
    # source's change has no resolution to run out of.
    if ! git merge-base --is-ancestor "$source_commit" "$page_commit" 2>/dev/null; then
        stale="$stale $source"
    fi
done

if [ -n "$stale" ]; then
    echo "-------------------------------------------------------------------------"
    echo "$PAGE was last built before the code that renders it:$stale"
    echo
    echo "  the page's last commit   ${page_commit:-none in this clone's history}"
    for source in $stale; do
        echo "  $source last changed in  $(commit_of "$source")"
    done
    echo
    echo "Rebuild it locally and commit the result — the command is in the"
    echo "\"Known gaps\" section of CLAUDE.md — or this pipeline publishes a report"
    echo "that does not match the code in the same commit."
    echo "-------------------------------------------------------------------------"
    exit 1
fi

echo "stale.sh: $PAGE is at least as new as:$SOURCES"
