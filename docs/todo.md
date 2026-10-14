# To do

Ideas agreed but not started. Newest last.

- **Planner: tasks kept in the browser (localStorage).** Save a planned task under a name
  and load it back later, alongside the XCTrack export and import (file, task code, QR
  code), so a task survives closing the page without going through XCTrack.
- **Planner: UX review — more on the map, a smaller panel.** Move more of the Task panel's
  buttons onto the map (as the 3D map's own controls now are) and shrink the panel, so
  the map gets more of the screen, on a phone especially.
- **Side view: a long press to read it, as the sounding has.** A finger on the side view
  should scroll the page like anywhere else; a tap reads a point, and a press held then
  dragged scrubs (`bindReader` in `meteo/js/meteo.js` is the pattern). Today a drag over
  the side view moves the cursor and the page does not scroll.
