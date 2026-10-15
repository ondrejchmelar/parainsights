#!/bin/sh
# Refuse to publish a report older than the code that renders it.
#
# `public/flights/index.html` is a committed build artifact: building it needs the IGC files, and
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

# Three pages, each against what renders it. The report needs the IGC files; the meteo
# and planner pages could be built in CI and were, until October 2026 — the planner page
# took 90 s of every deploy fetching its four sources, for data the monthly airspace job
# refreshes anyway (`airspace.yml` rebuilds it). So all three are committed artifacts
# now, built where they are changed, and this is what keeps that honest.
#
# Per page: the file, then everything whose output ends up inside it.
#
# The report: `airspaces`, `parainsights_common` and `parainsights_map` are in its list
# for the same reason as the viewer — it carries the nav strip as its header and the 3D
# map, with the airspace, in every flight, so a change to any of them leaves the
# published copy a version behind.
# The planner page is `airspaces.cli`'s, with the planner's section on it and the
# planner's scoring read out of `tracklog_viewer/js/xc.js`, and its sun (`sun.js`, `np.js`).
# One file inside those trees cannot change the report, and watching it made the guard
# fire on a change that could not possibly have mattered. `tracklog_viewer/cli.py` builds
# the report, so it stays watched; `airspaces/cli.py` is the *standalone* airspace page's
# command line, and the report imports `airspaces.build`, `.openair`, `.render_html`,
# `.scene` and `.sources` — never `.cli`. Check that list is still true before adding to
# this one: an exclusion that is wrong makes the whole check a decoration.
#
# `tracklog_viewer/js/build_runner.js` is watched: it is not in the page, but it is what
# the page's articles are rendered by. Everything else in `tracklog_viewer/js/` is inlined
# into the report (`render_html.JS_MODULES`) and is watched like any other renderer code.
REPORT_IGNORE=":(exclude)airspaces/cli.py"

commit_of() {
    # The last commit that touched a path, or nothing. A shallow CI clone may not reach
    # it, and that case is handled below rather than guessed at. $IGNORE is unquoted on
    # purpose: it is a list of pathspecs, none with a space in it.
    # shellcheck disable=SC2086
    git log -1 --format=%H -- "$1" $IGNORE 2>/dev/null || true
}

# Loudly, rather than shrugging. Without git this check answers "no idea" for every path
# and passes — which is indistinguishable from a fresh page, and is precisely the silent
# green pipeline the whole script exists to stop.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "stale.sh: no git history here, so freshness cannot be checked." >&2
    echo "stale.sh: install git, or run this from a clone." >&2
    exit 1
fi

failed=0
check() {
    PAGE=$1 SOURCES=$2 REBUILD=$3 IGNORE=${4:-}
    if [ ! -f "$PAGE" ]; then
        echo "stale.sh: no $PAGE — nothing to check" >&2
        return 0
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
        echo "Rebuild it locally and commit the result — $REBUILD — or this pipeline"
        echo "publishes a page that does not match the code in the same commit."
        echo "-------------------------------------------------------------------------"
        failed=1
        return 0
    fi

    echo "stale.sh: $PAGE contains the last change to:$SOURCES${IGNORE:+ ($IGNORE)}"
}

# The report's own code, the strip and the map. Not `airspaces` and `planner` since the
# published report links to the Planner page rather than embedding it (October 2026):
# only the embedded view imports them, and a planner change left the report "stale"
# with nothing in it to rebuild.
check public/flights/index.html "tracklog_viewer parainsights_common parainsights_map" \
    "the command is in the \"Known gaps\" section of CLAUDE.md"
check public/meteo/index.html "meteo parainsights_common" \
    "uv run python -m meteo.cli --html public/meteo/index.html"
check public/planner/index.html "airspaces planner parainsights_common parainsights_map tracklog_viewer/js/xc.js tracklog_viewer/js/np.js tracklog_viewer/js/sun.js" \
    "uv run python -m airspaces.cli --html public/planner/index.html (it fetches its sources)"
exit $failed
