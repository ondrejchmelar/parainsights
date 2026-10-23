#!/bin/sh
# The airspace page offers two downloads (the aerodrome zones and the circuits), and
# names the files rather than carrying them.
#
# The name carries the AIRAC date — `CZ_ATZ_20260806.txt`, `CZ_okruhy_20260806.txt` — so it changes
# every time the cycle does, and a rebuild that writes the page but not the file (or
# writes the file under a new name while an older page survives) leaves a button that
# 404s. `Refuse to publish a site with a dead link in its own nav` is already a commit in
# this repository's history; this is the same rule for the one link that is not in the nav.
set -eu

PAGE=public/planner/index.html
test -f "$PAGE" || { echo "download-link.sh: no $PAGE" >&2; exit 1; }

linked=$(grep -o 'href="CZ_\(ATZ\|okruhy\)_[0-9]*\.txt"' "$PAGE" | cut -d'"' -f2 | sort -u)
if [ "$(echo "$linked" | grep -c .)" -ne 2 ]; then
    echo "download-link.sh: the airspace page should offer two OpenAir files, offers: $linked" >&2
    exit 1
fi

for file in $linked; do
    if [ ! -f "public/planner/$file" ]; then
        echo "download-link.sh: the airspace page links $file, which is not beside it" >&2
        exit 1
    fi
    echo "download-link.sh: $file is there, $(wc -c < "public/planner/$file") bytes"
done
