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
from .view3d import (  # noqa: F401
    TILE_SOURCES,
    TRACK_TOLERANCE,
    cursor_track,
    data,
    panel,
)

__all__ = [
    "SCRIPT",
    "STYLE",
    "TILE_SOURCES",
    "TRACK_TOLERANCE",
    "cursor_track",
    "data",
    "panel",
]


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

var VERTEX = [
  'attribute vec3 aPos;',
  'attribute vec2 aUV;',
  'attribute vec3 aColour;',
  'uniform mat4 uMatrix;',
  'varying vec2 vUV;',
  'varying vec3 vColour;',
  'void main() {',
  '  vUV = aUV;',
  '  vColour = aColour;',
  '  gl_Position = uMatrix * vec4(aPos, 1.0);',
  '}'
].join('\\n');

// Either the draped imagery or the bare relief colour computed per vertex, chosen by a
// uniform rather than by a second program: the geometry is identical and switching
// styles is a button press, not a hot path.
var FRAGMENT = [
  'precision mediump float;',
  'uniform sampler2D uMap;',
  'uniform float uUseMap;',
  'varying vec2 vUV;',
  'varying vec3 vColour;',
  'void main() {',
  '  vec3 colour = uUseMap > 0.5 ? texture2D(uMap, vUV).rgb : vColour;',
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
  var uUseMap = gl.getUniformLocation(program, 'uUseMap');
  var aPos = gl.getAttribLocation(program, 'aPos');
  var aUV = gl.getAttribLocation(program, 'aUV');
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

  var uvBuffer = gl.createBuffer();
  var indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);

  // ---- texture ------------------------------------------------------------------

  var texture = null;
  var uploaded = null;      // the image object currently in the texture
  var mapped = null;        // the geographic box the UVs were built for
  var maxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);

  // Queried and reported but deliberately not used — see upload() for the measurements
  // that decided it. Kept so that turning mipmapping back on stays a one-line
  // experiment with a number attached rather than a guess.
  var aniso = gl.getExtension('EXT_texture_filter_anisotropic') ||
              gl.getExtension('WEBKIT_EXT_texture_filter_anisotropic') ||
              gl.getExtension('MOZ_EXT_texture_filter_anisotropic');
  var anisoMax = aniso
    ? gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT) : 1;

  // UVs come from the same linear lon/lat mapping sourceRect() uses in the 2D renderer,
  // which is what makes the imagery register with the grid cell for cell. They depend
  // on the *image's* box, not the DEM's: a stitched mosaic covers whole tiles and so
  // reaches past the terrain on every side.
  function buildUV(box) {
    var uv = new Float32Array(vertices * 2);
    var lonSpan = box.east - box.west;
    var latSpan = box.north - box.south;
    for (var r = 0; r < rows; r++) {
      var lat = dem.north - (dem.north - dem.south) * r / (rows - 1);
      var v = (box.north - lat) / latSpan;
      for (var c = 0; c < cols; c++) {
        var lon = dem.west + (dem.east - dem.west) * c / (cols - 1);
        var i = (r * cols + c) * 2;
        uv[i] = (lon - box.west) / lonSpan;
        uv[i + 1] = v;
      }
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, uvBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, uv, gl.STATIC_DRAW);
    mapped = box;
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

  function upload(image) {
    if (!texture) texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
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
    uploaded = image;
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
    if (image !== uploaded) upload(image);
    if (box !== mapped) buildUV(box);
    return true;
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
      depthBox = [[minX, maxX], [minY, maxY], [dem.min, dem.max]];
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
    var textured = withMap && syncTexture();

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

    bind(positionBuffer, aPos, 3);
    bind(colourBuffer, aColour, 3);
    if (textured) {
      bind(uvBuffer, aUV, 2);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(uMap, 0);
    } else if (aUV >= 0) {
      // Left enabled with no buffer bound, an attribute reads garbage; a constant is
      // both correct and free.
      gl.disableVertexAttribArray(aUV);
      gl.vertexAttrib2f(aUV, 0, 0);
    }

    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.drawElements(gl.TRIANGLES, cells * 6, indexType, 0);
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
      gl.deleteBuffer(uvBuffer);
      gl.deleteBuffer(indexBuffer);
      if (texture) gl.deleteTexture(texture);
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
    },
    stats: function () { return { cells: cells, folded: 0 }; },
    info: function () {
      return {
        active: true,
        version: isGL2 ? 'webgl2' : 'webgl',
        cells: cells,
        vertices: vertices,
        indexBits: wide ? 32 : 16,
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
