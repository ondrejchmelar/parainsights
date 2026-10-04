"""A WebGL heightfield for the 3D view, and only the heightfield.

`view3d.py` draws its terrain by walking the DEM cell by cell and fitting an affine
texture map to each projected quad. That is the best canvas 2D can do, and it is not
good enough: painter's order has no depth buffer, so a cell whose quad turns inside out
— a slope steeper than the pitch angle — cannot be drawn correctly by *any* per-cell
treatment. Four were tried. Each one traded a wedge for a lattice, a hole or a smear.

A depth buffer removes the problem instead of mitigating it. There stops being such a
thing as a folded cell: there are triangles, and the near one wins per pixel. The same
change collapses ~5 200 `drawImage` calls into one `drawElements`.

This is allowed where MapLibre and deck.gl are not, because a shader is a string in the
document. Nothing is fetched, so the content-security policy that shapes every other
decision in `view3d.py` has nothing to object to.

**What this module is not.** It is not a second copy of the viewer. The camera, the
gestures, the tile stitching, the basemap cycling and the test probes all stay in
`view3d.py`, which registers this as a *backend* for the one function a depth buffer
changes. Two consequences worth knowing:

- The camera is not reimplemented, it is *read*. `view` and `fit` are held by reference
  and the matrix below is derived from them each frame, so `groundUnder()`/`holdGround()`
  keep inverting the projection the gestures anchor through. A reimplementation would
  have had to stay bit-compatible with those by hand.
- The track, the climb markers and the cursor stay in 2D on the canvas that is already
  there, which now sits transparent *over* the GL one. That keeps `initFlight`'s chart
  linking untouched, and it is the cheap half of the frame anyway.
"""

# The payload, the markup and the controls are unchanged — this replaces how the
# heightfield is drawn, not what is in the document. Re-exported so a caller can treat
# the two modules as one surface.
from .view3d import TILE_SOURCES, panel  # noqa: F401

__all__ = ["SCRIPT", "STYLE", "TILE_SOURCES", "panel"]


STYLE = """
/* The GL canvas goes behind the one that is already in the markup, which keeps the
   track, the markers and the cursor in 2D and keeps every pointer handler where it was.
   Only applied once a context actually exists, so a browser without WebGL — or one that
   has just lost its context — is left with the original opaque canvas. */
.view3d-panel.has-gl canvas.view3d { background: none; position: relative; z-index: 1; }
.view3d-panel.has-gl canvas.view3d-gl {
  position: absolute; inset: 0; display: block; width: 100%; height: 100%;
  /* The sky. It moves here because the 2D canvas above must be transparent to show
     the terrain through it. */
  background: linear-gradient(180deg, var(--panel-2) 0%, var(--panel) 62%); z-index: 0; }
/* Positioning the GL canvas puts it in the same stacking level as the controls, which
   are positioned too. Say which is on top rather than relying on document order. */
.view3d-panel.has-gl .view3d-controls,
.view3d-panel.has-gl .view3d-credit,
.view3d-panel.has-gl .view3d-earth { z-index: 2; }
"""


SCRIPT = """
// Registers a terrain backend for initView3d(). Returning null at any point leaves the
// canvas renderer in charge, which is the supported outcome and not a failure.
(function () {

// `aGeo` is the node's position in the *DEM's* box, 0..1 east and 0..1 south. It is a
// property of the grid alone, so the buffer is built once and never rebuilt — where the
// old `aUV` was built against the image's box and had to be regenerated every time a
// mosaic finished stitching. Each image's box now arrives as a uniform instead, which is
// what makes it cheap to have two of them at once.
var VERTEX = [
  'attribute vec3 aPos;',
  'attribute vec2 aGeo;',
  'attribute vec3 aColour;',
  'uniform mat4 uMatrix;',
  'varying vec2 vGeo;',
  'varying vec3 vColour;',
  'void main() {',
  '  vGeo = aGeo;',
  '  vColour = aColour;',
  '  gl_Position = uMatrix * vec4(aPos, 1.0);',
  '}'
].join('\\n');

// Either the draped imagery or the bare relief colour computed per vertex, chosen by a
// uniform rather than by a second program: the geometry is identical and switching
// styles is a button press, not a hot path.
//
// Two draped images, not one. The base mosaic covers the whole terrain at whatever zoom
// its tile budget reached; the *detail* mosaic covers only what the reader has zoomed in
// on, at a zoom several steps finer. Where a fragment falls inside the detail box it
// wins, and outside it the base carries on — so the terrain is textured everywhere and
// sharp where it is being looked at.
//
// `uBox` and `uDetailBox` are (scaleX, scaleY, offsetX, offsetY), taking a DEM-space
// position to that image's UV. The edge is feathered over `EDGE` of the detail box
// rather than switched, because a hard boundary between two zoom levels of the same
// imagery is a visible rectangle drawn across the ground — the seam reads as a bug even
// though both halves are correct.
var FRAGMENT = [
  'precision mediump float;',
  'uniform sampler2D uMap;',
  'uniform sampler2D uDetailMap;',
  'uniform vec4 uBox;',
  'uniform vec4 uDetailBox;',
  'uniform float uUseMap;',
  'uniform float uUseDetail;',
  'uniform vec4 uHole;',
  'uniform float uUseHole;',
  'varying vec2 vGeo;',
  'varying vec3 vColour;',
  'const float EDGE = 0.03;',
  'void main() {',
  // Where the detail terrain is drawn the base mesh is not: two surfaces a few metres
  // apart would fight in the depth buffer. `uHole` is (west, north, east, south) in the
  // same 0..1 DEM box as `vGeo`.
  '  if (uUseHole > 0.5 && vGeo.x > uHole.x && vGeo.x < uHole.z',
  '      && vGeo.y > uHole.y && vGeo.y < uHole.w) discard;',
  '  vec3 colour = vColour;',
  '  if (uUseMap > 0.5) {',
  '    colour = texture2D(uMap, vGeo * uBox.xy + uBox.zw).rgb;',
  '    if (uUseDetail > 0.5) {',
  '      vec2 d = vGeo * uDetailBox.xy + uDetailBox.zw;',
  '      vec2 edge = min(d, 1.0 - d);',
  '      float inside = smoothstep(0.0, EDGE, min(edge.x, edge.y));',
  '      colour = mix(colour, texture2D(uDetailMap, clamp(d, 0.0, 1.0)).rgb, inside);',
  '    }',
  '  }',
  '  gl_FragColor = vec4(colour, 1.0);',
  '}'
].join('\\n');

function compile(gl, type, source) {
  var shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function link(gl) {
  var vertex = compile(gl, gl.VERTEX_SHADER, VERTEX);
  var fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
  if (!vertex || !fragment) return null;
  var program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

function backend(host) {
  var dem = host.dem, cols = host.cols, rows = host.rows;
  if (cols < 2 || rows < 2) return null;

  var canvas = document.createElement('canvas');
  canvas.className = 'view3d-gl';
  // Decorative: everything it draws is described by the panel's own aria-label, and the
  // 2D canvas above it keeps that label.
  canvas.setAttribute('aria-hidden', 'true');

  // alpha, so the CSS sky gradient shows through where there is no terrain.
  // preserveDrawingBuffer, because a headless screenshot is taken outside the draw call
  // and comes back blank without it — and "render the report and look at it" is how
  // several real bugs in this view were found. The copy it costs is affordable at one
  // draw call a frame.
  var attributes = {
    alpha: true, depth: true, antialias: true, preserveDrawingBuffer: true
  };
  var gl = canvas.getContext('webgl2', attributes) ||
           canvas.getContext('webgl', attributes);
  if (!gl) return null;

  var isGL2 = typeof WebGL2RenderingContext !== 'undefined' &&
              gl instanceof WebGL2RenderingContext;

  // 26 000 DEM nodes is past the 65 536 a 16-bit index can address, so most real grids
  // need 32-bit indices. WebGL2 always has them; WebGL1 needs the extension, and
  // without it the canvas renderer is the better answer.
  var vertices = cols * rows;
  var wide = vertices > 65536;
  if (wide && !isGL2 && !gl.getExtension('OES_element_index_uint')) return null;

  var program = link(gl);
  if (!program) return null;

  var uMatrix = gl.getUniformLocation(program, 'uMatrix');
  var uMap = gl.getUniformLocation(program, 'uMap');
  var uDetailMap = gl.getUniformLocation(program, 'uDetailMap');
  var uBox = gl.getUniformLocation(program, 'uBox');
  var uDetailBox = gl.getUniformLocation(program, 'uDetailBox');
  var uUseMap = gl.getUniformLocation(program, 'uUseMap');
  var uUseDetail = gl.getUniformLocation(program, 'uUseDetail');
  var uHole = gl.getUniformLocation(program, 'uHole');
  var uUseHole = gl.getUniformLocation(program, 'uUseHole');
  var aPos = gl.getAttribLocation(program, 'aPos');
  var aGeo = gl.getAttribLocation(program, 'aGeo');
  var aColour = gl.getAttribLocation(program, 'aColour');

  // ---- geometry -----------------------------------------------------------------
  //
  // One vertex per DEM node in the same local metric frame the canvas renderer uses —
  // x east, y north, z the elevation in metres, unexaggerated. The vertical
  // exaggeration and the whole camera live in the matrix, so nothing here is rebuilt
  // when the reader tilts, zooms or presses ×2.

  var position = new Float32Array(vertices * 3);
  var colour = new Float32Array(vertices * 3);
  var relief = Math.max(dem.max - dem.min, 1);
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;

  for (var r = 0; r < rows; r++) {
    for (var c = 0; c < cols; c++) {
      var i = r * cols + c;
      var x = host.nodeX[i], y = host.nodeY[i], z = dem.z[i];
      position[i * 3] = x;
      position[i * 3 + 1] = y;
      position[i * 3 + 2] = z;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  // Bare relief, the same curve as view3d.py's shade(): hillshade stretched to this
  // terrain's own lit range, then an elevation tint. Per vertex rather than per cell, so
  // the browser interpolates it and the facets the 2D version shows are gone for free.
  //
  // Its own function because the light moves: hovering the charts re-lights the
  // terrain for that moment of the flight, and the host calls `relight()` rather than
  // rebuilding the whole backend. The lit range is re-read from the host each time,
  // since it is measured against the same light.
  function shadeVertices() {
    var lit = host.lit();
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var i = r * cols + c;
        var shade = 0.96;
        if (lit.spread > 0) {
          var t = (host.shadeFactor(r, c) - lit.mid) / lit.spread;
          shade = 0.86 + Math.max(-1, Math.min(1, t)) * 0.30;
        }
        var height = Math.min(1, Math.max(0, (dem.z[i] - dem.min) / relief));
        colour[i * 3] = (120 + height * 95) * shade / 255;
        colour[i * 3 + 1] = (135 + height * 80) * shade / 255;
        colour[i * 3 + 2] = (105 + height * 95) * shade / 255;
      }
    }
  }
  shadeVertices();

  var cells = (cols - 1) * (rows - 1);
  var indices = wide ? new Uint32Array(cells * 6) : new Uint16Array(cells * 6);
  var at = 0;
  for (var rr = 0; rr < rows - 1; rr++) {
    for (var cc = 0; cc < cols - 1; cc++) {
      var i00 = rr * cols + cc;
      var i01 = i00 + 1;
      var i10 = i00 + cols;
      var i11 = i10 + 1;
      indices[at++] = i00; indices[at++] = i01; indices[at++] = i11;
      indices[at++] = i00; indices[at++] = i11; indices[at++] = i10;
    }
  }
  var indexType = wide ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT;

  var positionBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, position, gl.STATIC_DRAW);

  var colourBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, colourBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, colour, gl.STATIC_DRAW);

  var geoBuffer = gl.createBuffer();
  var indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);

  // ---- texture ------------------------------------------------------------------

  var texture = null;
  var uploaded = null;            // the image object currently in the base texture
  var detailTexture = null;
  var detailUploaded = null;      // and in the detail texture
  var maxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);

  // Queried and reported but deliberately not used — see upload() for the measurements
  // that decided it. Kept so that turning mipmapping back on stays a one-line
  // experiment with a number attached rather than a guess.
  var aniso = gl.getExtension('EXT_texture_filter_anisotropic') ||
              gl.getExtension('WEBKIT_EXT_texture_filter_anisotropic') ||
              gl.getExtension('MOZ_EXT_texture_filter_anisotropic');
  var anisoMax = aniso
    ? gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT) : 1;

  // The node's place in the DEM's own box, which is a property of the grid and of
  // nothing else — so this is built once, at startup, and a mosaic finishing does not
  // touch it. The linear lon/lat mapping is the one `sourceRect()` uses in the 2D
  // renderer, which is what makes the imagery register with the grid cell for cell.
  (function buildGeo() {
    var geo = new Float32Array(vertices * 2);
    for (var r = 0; r < rows; r++) {
      var v = r / (rows - 1);
      for (var c = 0; c < cols; c++) {
        var i = (r * cols + c) * 2;
        geo[i] = c / (cols - 1);
        geo[i + 1] = v;
      }
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, geoBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, geo, gl.STATIC_DRAW);
  })();

  // An image's box as (scaleX, scaleY, offsetX, offsetY), so that
  // `uv = aGeo * scale + offset`. A stitched mosaic covers whole tiles and reaches past
  // the terrain on every side, so the scale is normally under 1 for the base image and
  // well over 1 for a detail mosaic covering a corner of it.
  function boxUniform(box) {
    var lonSpan = box.east - box.west;
    var latSpan = box.north - box.south;
    var demLon = dem.east - dem.west;
    var demLat = dem.north - dem.south;
    return [
      demLon / lonSpan,
      demLat / latSpan,
      (dem.west - box.west) / lonSpan,
      (box.north - dem.north) / latSpan
    ];
  }

  // A stitched mosaic can be bigger than the driver will take. Downscaling is better
  // than refusing the style: the alternative is a terrain with no imagery on it.
  function withinLimit(image) {
    var width = image.naturalWidth || image.width;
    var height = image.naturalHeight || image.height;
    if (width <= maxTexture && height <= maxTexture) return image;
    var factor = maxTexture / Math.max(width, height);
    var scaled = document.createElement('canvas');
    scaled.width = Math.max(1, Math.floor(width * factor));
    scaled.height = Math.max(1, Math.floor(height * factor));
    scaled.getContext('2d').drawImage(image, 0, 0, scaled.width, scaled.height);
    return scaled;
  }

  // Both textures go up the same way. `unit` picks which one, so the detail mosaic
  // inherits every decision below — the clamp, the LINEAR filter and the absence of
  // mipmaps — rather than acquiring its own set by accident.
  function upload(image, detail) {
    var handle = detail ? detailTexture : texture;
    if (!handle) {
      handle = gl.createTexture();
      if (detail) detailTexture = handle; else texture = handle;
    }
    gl.bindTexture(gl.TEXTURE_2D, handle);
    // The basemap's first row is its northern edge and v = 0 is north, so the default
    // unflipped upload is the one that lines up.
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE,
                  withinLimit(image));
    // Clamped and unmipped is the only combination WebGL1 allows for a
    // non-power-of-two texture, and a stitched mosaic is never a power of two.
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    // No mipmaps. This was measured, not assumed, and the assumption was wrong.
    //
    // Terrain is looked at from a grazing angle, and mip level is chosen from the
    // *longest* texture derivative. At pitch 0.20 a pixel's footprint on the ground is
    // enormously elongated, so an isotropic lookup blurs by the long axis in both
    // directions and throws away the short axis, which is where the detail is. On the
    // Blatná flight at zoom 4 / pitch 0.20, measured as the Laplacian variance of the
    // rendered panel against the canvas renderer it replaces:
    //
    //     canvas 2D (no mipmaps)          1363   near ground 1788
    //     mipmapped, isotropic             596   near ground  665
    //     mipmapped, 16x anisotropic       874   near ground 1114
    //     no mipmaps (this)               1336   near ground 1802
    //
    // Anisotropy recovers only about half of it on a software rasteriser, and the
    // difference is not subtle to look at: the imagery goes soft and the terrain goes
    // *flat*, because shadedTexture() bakes the hillshade into the very texture being
    // blurred away. Plain LINEAR is exactly what the 2D path does, which means this
    // renderer cannot come out worse than the one it replaces — and the texture is
    // close to 1:1 at the cameras that matter, so there is little aliasing to save.
    // The extension is still queried and reported, so a future change here is
    // measurable rather than a guess.
    if (detail) detailUploaded = image; else uploaded = image;
  }

  // Noticed by identity rather than by being told: the style cycles, a mosaic finishes
  // stitching, an embedded image decodes — three paths that all end in `basemap` being
  // a different object, and none of which should have to know this module exists.
  function syncTexture() {
    var image = host.texture();
    var box = host.textureBox();
    if (!image || !box) return false;
    var width = image.naturalWidth || image.width;
    if (!width) return false;
    if (image !== uploaded) upload(image, false);
    return boxUniform(box);
  }

  // The sharper mosaic over whatever the reader has zoomed in on, or null. Absent for
  // the whole life of a panel nobody zooms into, which is why it is asked for by the
  // same identity check the base image uses rather than being pushed in.
  function syncDetail() {
    if (!host.detail) return null;
    var patch = host.detail();
    if (!patch || !patch.image || !patch.box) return null;
    var width = patch.image.naturalWidth || patch.image.width;
    if (!width) return null;
    if (patch.image !== detailUploaded) upload(patch.image, true);
    return boxUniform(patch.box);
  }

  // ---- detail terrain -----------------------------------------------------------
  //
  // A finer grid over the part of the terrain the reader has zoomed in on, fetched by
  // the host (`terrainPlan` in view3d.py). Its own buffers, the same program: the vertex
  // `aGeo` is its place in the *base* DEM's box, so both imagery textures land on it
  // exactly as they land on the base mesh, and the base mesh is cut away under it.
  var patch = null;               // the host's patch object currently in the buffers
  var patchCells = 0, patchColour = null, patchHole = null;
  var patchPosition = gl.createBuffer(), patchColourBuffer = gl.createBuffer();
  var patchGeo = gl.createBuffer(), patchIndex = gl.createBuffer();

  function shadePatch() {
    if (!patch) return;
    var lit = host.lit();
    var pc = patch.cols, pr = patch.rows, z = patch.z;
    var a = host.toMetres(patch.west, patch.north);
    var b = host.toMetres(patch.east, patch.south);
    var cellX = (b[0] - a[0]) / (pc - 1), cellY = (a[1] - b[1]) / (pr - 1);
    for (var r = 0; r < pr; r++) {
      for (var c = 0; c < pc; c++) {
        var i = r * pc + c;
        var right = z[i + (c + 1 < pc ? 1 : 0)], below = z[i + (r + 1 < pr ? pc : 0)];
        var shade = 0.96;
        if (lit.spread > 0) {
          var t = (host.slopeShade((right - z[i]) / cellX, (below - z[i]) / cellY)
                   - lit.mid) / lit.spread;
          shade = 0.86 + Math.max(-1, Math.min(1, t)) * 0.30;
        }
        // Tinted against the *base* terrain's range, so the patch is the same colour as
        // the ground around it.
        var height = Math.min(1, Math.max(0, (z[i] - dem.min) / relief));
        patchColour[i * 3] = (120 + height * 95) * shade / 255;
        patchColour[i * 3 + 1] = (135 + height * 80) * shade / 255;
        patchColour[i * 3 + 2] = (105 + height * 95) * shade / 255;
      }
    }
  }

  function setTerrainDetail(next) {
    patch = next && next.z && next.cols > 1 && next.rows > 1 ? next : null;
    depthBox = null;
    if (!patch) { patchCells = 0; return; }
    var pc = patch.cols, pr = patch.rows, count = pc * pr;
    var lonSpan = dem.east - dem.west, latSpan = dem.north - dem.south;
    var positions = new Float32Array(count * 3), geo = new Float32Array(count * 2);
    for (var r = 0; r < pr; r++) {
      var lat = patch.north - (patch.north - patch.south) * r / (pr - 1);
      for (var c = 0; c < pc; c++) {
        var lon = patch.west + (patch.east - patch.west) * c / (pc - 1);
        var i = r * pc + c, m = host.toMetres(lon, lat);
        positions[i * 3] = m[0]; positions[i * 3 + 1] = m[1]; positions[i * 3 + 2] = patch.z[i];
        geo[i * 2] = (lon - dem.west) / lonSpan;
        geo[i * 2 + 1] = (dem.north - lat) / latSpan;
      }
    }
    patchColour = new Float32Array(count * 3);
    shadePatch();
    var wideIndex = count > 65536;
    patchCells = (pc - 1) * (pr - 1);
    var index = wideIndex ? new Uint32Array(patchCells * 6) : new Uint16Array(patchCells * 6);
    var k = 0;
    for (var rr = 0; rr < pr - 1; rr++) {
      for (var cc = 0; cc < pc - 1; cc++) {
        var i00 = rr * pc + cc, i01 = i00 + 1, i10 = i00 + pc, i11 = i10 + 1;
        index[k++] = i00; index[k++] = i01; index[k++] = i11;
        index[k++] = i00; index[k++] = i11; index[k++] = i10;
      }
    }
    patch.indexType = wideIndex ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT;
    gl.bindBuffer(gl.ARRAY_BUFFER, patchPosition);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, patchColourBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, patchColour, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, patchGeo);
    gl.bufferData(gl.ARRAY_BUFFER, geo, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, patchIndex);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, index, gl.STATIC_DRAW);
    // The hole is the patch less one base cell on every side, so the two meshes overlap
    // by a cell rather than meeting at an edge: where a finer grid and a coarser one
    // disagree about a height, an edge would open a slit of sky between them.
    var insetX = 1 / (cols - 1), insetY = 1 / (rows - 1);
    patchHole = [(patch.west - dem.west) / lonSpan + insetX,
                 (dem.north - patch.north) / latSpan + insetY,
                 (patch.east - dem.west) / lonSpan - insetX,
                 (dem.north - patch.south) / latSpan - insetY];
  }

  // ---- camera -------------------------------------------------------------------
  //
  // The canvas renderer's projection, written as a matrix. Reading it against
  // view3d.py's world()/project():
  //
  //   wx = x·cos yaw − y·sin yaw
  //   wy = x·sin yaw + y·cos yaw
  //   wz = (z − dem.min)·vertical
  //   sx = fit.dx + wx·scale + panX
  //   sy = fit.dy + (−wy·sin pitch − wz·cos pitch)·scale + panY
  //
  // and the depth axis is the one drawTerrain() already sorts on,
  // d = wy·cos pitch − wz·sin pitch, which is the direction into the screen once the
  // pitch is applied. All three are linear in x, y and z, so one 4×4 does the lot and
  // the projection stays orthographic — which it must, because groundUnder() inverts it
  // in closed form.

  var depthBox = null;

  function depthRange(dx, dy, dz, dc) {
    if (!depthBox) {
      // The patch can reach a little past the base grid's heights: a finer DEM finds the
      // summit a coarse one averaged away, and the bottom of the valley too.
      depthBox = [[minX, maxX], [minY, maxY],
                  [Math.min(dem.min, patch ? patch.min : dem.min),
                   Math.max(dem.max, patch ? patch.max : dem.max)]];
    }
    var worst = 0;
    for (var a = 0; a < 2; a++) {
      for (var b = 0; b < 2; b++) {
        for (var e = 0; e < 2; e++) {
          var d = Math.abs(dx * depthBox[0][a] + dy * depthBox[1][b] +
                           dz * depthBox[2][e] + dc);
          if (d > worst) worst = d;
        }
      }
    }
    // A margin, so a vertex exactly on the far corner is not clipped by rounding.
    return worst * 1.02 + 1;
  }

  function matrix() {
    var size = host.size();
    var W = size[0], H = size[1];
    var view = host.view, fit = host.fit;
    var cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    var cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    var k = fit.scale, vertical = view.vertical, base = dem.min;

    // sx = Ax·x + Ay·y + Ac
    var Ax = k * cy, Ay = -k * sy, Ac = fit.dx + view.panX;
    // sy = Bx·x + By·y + Bz·z + Bc
    var Bx = -k * sy * sp, By = -k * cy * sp, Bz = -k * vertical * cp;
    var Bc = fit.dy + view.panY + k * vertical * base * cp;
    // d = Dx·x + Dy·y + Dz·z + Dc, larger being farther away
    var Dx = sy * cp, Dy = cy * cp, Dz = -vertical * sp, Dc = vertical * base * sp;

    var half = depthRange(Dx, Dy, Dz, Dc);

    // Canvas pixels to clip space. Screen y grows downward and clip y grows upward,
    // hence the negation on the whole second row.
    var px = 2 / Math.max(W, 1), py = 2 / Math.max(H, 1);
    return new Float32Array([
      px * Ax, -py * Bx, Dx / half, 0,
      px * Ay, -py * By, Dy / half, 0,
      0, -py * Bz, Dz / half, 0,
      px * Ac - 1, 1 - py * Bc, Dc / half, 1
    ]);
  }

  // ---- drawing ------------------------------------------------------------------

  var W = 0, H = 0;

  function resize(width, height) {
    W = width;
    H = height;
    canvas.width = width;
    canvas.height = height;
  }

  function bind(buffer, location, size) {
    if (location < 0) return;      // optimised out of the program
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
  }

  function terrain(withMap) {
    var size = host.size();
    if (size[0] !== W || size[1] !== H) resize(size[0], size[1]);
    var box = withMap ? syncTexture() : null;
    var textured = !!box;
    var detail = textured ? syncDetail() : null;

    gl.viewport(0, 0, W, H);
    gl.clearColor(0, 0, 0, 0);          // the sky is the canvas's CSS background
    gl.clearDepth(1);
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.disable(gl.BLEND);
    // No face culling: the reader can orbit to any yaw, so a cell's winding flips
    // depending on which side of the terrain they are standing. The depth buffer is
    // what resolves the overlap, and it does not care which way round a triangle is.
    gl.disable(gl.CULL_FACE);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    gl.useProgram(program);
    gl.uniformMatrix4fv(uMatrix, false, matrix());
    gl.uniform1f(uUseMap, textured ? 1 : 0);
    gl.uniform1f(uUseDetail, detail ? 1 : 0);

    bind(positionBuffer, aPos, 3);
    bind(colourBuffer, aColour, 3);
    if (textured) {
      bind(geoBuffer, aGeo, 2);
      gl.uniform4f(uBox, box[0], box[1], box[2], box[3]);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(uMap, 0);
      if (detail) {
        gl.uniform4f(uDetailBox, detail[0], detail[1], detail[2], detail[3]);
        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, detailTexture);
        gl.uniform1i(uDetailMap, 1);
      }
    } else if (aGeo >= 0) {
      // Left enabled with no buffer bound, an attribute reads garbage; a constant is
      // both correct and free.
      gl.disableVertexAttribArray(aGeo);
      gl.vertexAttrib2f(aGeo, 0, 0);
    }

    var holed = patch && patchCells && patchHole[2] > patchHole[0]
                && patchHole[3] > patchHole[1];
    if (holed) {
      // The hole is tested in the fragment shader against vGeo, which an untextured
      // draw leaves constant — so the base mesh needs its real geometry for this.
      bind(geoBuffer, aGeo, 2);
      gl.uniform4f(uHole, patchHole[0], patchHole[1], patchHole[2], patchHole[3]);
    }
    gl.uniform1f(uUseHole, holed ? 1 : 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.drawElements(gl.TRIANGLES, cells * 6, indexType, 0);

    if (patch && patchCells) {
      gl.uniform1f(uUseHole, 0);
      bind(patchPosition, aPos, 3);
      bind(patchColourBuffer, aColour, 3);
      bind(patchGeo, aGeo, 2);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, patchIndex);
      gl.drawElements(gl.TRIANGLES, patchCells * 6, patch.indexType, 0);
    }
  }

  // ---- mounting and coming back off ---------------------------------------------

  var panel = host.canvas.closest('.view3d-panel') || host.canvas.parentNode;

  function detach() {
    if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
    if (panel.classList) panel.classList.remove('has-gl');
  }

  var disposed = false;

  // Context loss happens for real on a phone — a background tab, a driver reset, or
  // simply too many panels in one document — and a blank panel is a worse outcome than
  // a slower one. Not prevented and not waited out: hand the heightfield back to the 2D
  // renderer, which needs nothing from us.
  canvas.addEventListener('webglcontextlost', function () {
    // dispose() loses the context on purpose. Falling back then would redraw a panel
    // that is on its way out of the document.
    if (disposed) return;
    detach();
    host.fallback();
  });

  var api = {
    terrain: terrain,
    resize: resize,
    detach: detach,
    // A browser allows a page only about sixteen live WebGL contexts, and flights
    // accumulate: upload four tracks, remove them, upload four more, and a document
    // that leaked a context per panel would run out and quietly serve everybody the
    // 2D renderer instead. Dropping the canvas is not enough — the context outlives it
    // until the collector gets round to it — so the loss is forced.
    dispose: function () {
      if (disposed) return;
      disposed = true;
      gl.deleteBuffer(positionBuffer);
      gl.deleteBuffer(colourBuffer);
      gl.deleteBuffer(geoBuffer);
      gl.deleteBuffer(indexBuffer);
      gl.deleteBuffer(patchPosition);
      gl.deleteBuffer(patchColourBuffer);
      gl.deleteBuffer(patchGeo);
      gl.deleteBuffer(patchIndex);
      if (texture) gl.deleteTexture(texture);
      if (detailTexture) gl.deleteTexture(detailTexture);
      gl.deleteProgram(program);
      var lose = gl.getExtension('WEBGL_lose_context');
      if (lose) lose.loseContext();
      detach();
    },
    // The sun moved. Only the vertex colours carry the bare-relief shading, so that is
    // all there is to redo here — the draped texture is shaded on the host's side and
    // arrives through `texture()` as usual. `bufferSubData` rather than a fresh buffer:
    // the geometry is untouched and the attribute layout is the same.
    relight: function () {
      if (disposed) return;
      shadeVertices();
      gl.bindBuffer(gl.ARRAY_BUFFER, colourBuffer);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, colour);
      if (patch) {
        shadePatch();
        gl.bindBuffer(gl.ARRAY_BUFFER, patchColourBuffer);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, patchColour);
      }
    },
    setTerrainDetail: setTerrainDetail,
    stats: function () { return { cells: cells, folded: 0 }; },
    info: function () {
      return {
        active: true,
        version: isGL2 ? 'webgl2' : 'webgl',
        cells: cells,
        vertices: vertices,
        indexBits: wide ? 32 : 16,
        patchCells: patchCells,
        textured: !!uploaded,
        anisotropy: anisoMax,
        // Read back from the texture rather than reported from a literal, so it is a
        // statement about what the renderer is doing and not about what a comment says
        // it does. gl.LINEAR (9729) means no mipmapping — see upload().
        minFilter: texture ? (function () {
          gl.bindTexture(gl.TEXTURE_2D, texture);
          return gl.getTexParameter(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER);
        })() : null,
        depthBits: gl.getParameter(gl.DEPTH_BITS),
        maxTexture: maxTexture
      };
    },
    // The matrix applied to one world point, in the same canvas pixels project()
    // returns, so a test can hold the two against each other. Measured against the
    // live box rather than the cached one, so it is readable before the first frame.
    screenOf: function (x, y, z) {
      var m = matrix();
      var size = host.size();
      var clipX = m[0] * x + m[4] * y + m[8] * z + m[12];
      var clipY = m[1] * x + m[5] * y + m[9] * z + m[13];
      return [(clipX + 1) / 2 * size[0], (1 - clipY) / 2 * size[1]];
    },
    // Exposed for tests: the clip-space depth of a world point. Ordering by this is
    // what replaces the painter's-order sort, so it has to be checkable — and it has
    // to stay inside [-1, 1] or the far terrain is clipped away.
    depthOf: function (x, y, z) {
      var m = matrix();
      return m[2] * x + m[6] * y + m[10] * z + m[14];
    }
  };

  // Mounted last, so that any failure above leaves the document exactly as it was and
  // the canvas renderer simply carries on.
  host.canvas.parentNode.insertBefore(canvas, host.canvas);
  if (panel.classList) panel.classList.add('has-gl');
  return api;
}

window.__view3dBackend = function (host) {
  try {
    return backend(host);
  } catch (error) {
    // Any failure at all leaves the canvas renderer in charge. There is no state to
    // unwind — nothing has replaced anything until a backend is returned.
    return null;
  }
};

})();
"""
