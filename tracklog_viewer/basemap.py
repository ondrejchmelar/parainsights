"""An embedded basemap image: the payload shape `view3d` drapes over its terrain.

Pages fetch their imagery at view time now (`view3d.TILE_SOURCES`), and the build-time
stitcher that used to fill this in went with `--embed`, which nothing used. The shape
stays because the 3D view still accepts an embedded image, and its tests hand it one.
"""

from dataclasses import dataclass


@dataclass
class Basemap:
    """A stitched raster image and the exact geographic box it covers."""

    west: float
    east: float
    south: float
    north: float
    data_uri: str
    width: int
    height: int
    zoom: int
    attribution: str = ""

    def to_dict(self) -> dict:
        return {
            "west": round(self.west, 6),
            "east": round(self.east, 6),
            "south": round(self.south, 6),
            "north": round(self.north, 6),
            "uri": self.data_uri,
            "zoom": self.zoom,
            "attribution": self.attribution,
        }
