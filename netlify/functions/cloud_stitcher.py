import rasterio
from rasterio.windows import window_from_bounds
import numpy as np

def fetch_and_stitch_elevation(bounds, sample_cog_url):
    """
    Step B2: Performs an HTTP range request against a cloud-optimized elevation source
    using the bounding box, streaming only the required sub-region into a memory grid.
    """
    # Open a connection to the cloud raster dataset via HTTP virtual file system
    with rasterio.open(sample_cog_url) as src:
        # Convert geographic bounds (south, north, west, east) to a raster pixel window
        window = window_from_bounds(
            bounds['west'], bounds['south'], 
            bounds['east'], bounds['north'], 
            transform=src.transform
        )
        
        # Stream ONLY the data bytes for this specific window into a NumPy array in RAM
        elevation_grid = src.read(1, window=window)
        
        # Get the new spatial transform corresponding to this clipped window
        window_transform = rasterio.windows.transform(window, src.transform)
        
        return elevation_grid, window_transform