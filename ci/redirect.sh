#!/bin/sh
# Turn `public/` into a site that only says "moved", for the deprecated GitLab Pages.
#
# The site lives on GitHub Pages now. GitLab Pages cannot answer with a real redirect to
# another host — its `_redirects` rules stay on the same domain — so every page is
# replaced by a stub that sends the reader on with the same path, query and anchor: a
# bookmarked `…/meteo/` lands on the new `…/meteo/`, not on the front page.
#
# `404.html` is the same stub, and it is what catches every other path — the OpenAir
# download, an old link to a page that no longer exists. The `<meta refresh>` is for a
# reader with no JavaScript, who gets the front page rather than nothing.
set -eu

TARGET=https://ondrejchmelar.github.io/parainsights

test -d public || { echo "redirect.sh: no public/ to replace" >&2; exit 1; }
pages=$(cd public && find . -name '*.html' | sed 's#^\./##')

rm -rf public
mkdir public
for page in $pages 404.html; do
    mkdir -p "public/$(dirname "$page")"
    cat > "public/$page" <<EOF
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>parainsights has moved</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="$TARGET/">
<meta http-equiv="refresh" content="0; url=$TARGET/">
<script>
  // The path under the project, whichever way GitLab served it: /meteo/ on the unique
  // domain (parainsights-55df51.gitlab.io), /parainsights/meteo/ on the namespace one.
  var path = location.pathname.replace(/^\/parainsights(?=\/|$)/, "");
  location.replace("$TARGET" + (path || "/") + location.search + location.hash);
</script>
<p>parainsights has moved to <a href="$TARGET/">$TARGET/</a>.</p>
EOF
done
echo "redirect.sh: $(echo $pages 404.html | wc -w) pages now point at $TARGET"
