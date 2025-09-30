import pandas as pd
import geopandas as gpd
import fiona
import leafmap.foliumap as leafmap

def filter_non_intersecting_lines(first_data_filepath, second_data_filepath):
    """
    This generates the difference between two lines, the first being less complete than the second
    It checks for the lines that intersects and takes them out leaving the second lines that do not intersect with the first
    The difference is also plotted
    :param first_data_filepath: fewer linestrings
    :param second_data_filepath: the data with a lot of linestrings
    :return: the difference between the 2 linestrings
    """

    # load layers from the first dataset
    layers = fiona.listlayers(first_data_filepath)
    gdf = [gpd.read_file(first_data_filepath, layer=lyr) for lyr in layers]
    print(f"The layers are {layers}")

    # Merge the layers in the first dataset into one GeoDataFrame
    gdf_1 = gpd.GeoDataFrame(pd.concat(gdf, ignore_index=True), crs=gdf[0].crs)

    # Load customer coverage lines
    gdf_2 = gpd.read_file(second_data_filepath)

    # Make sure they’re in the same CRS
    gdf_2 = gdf_2.to_crs(gdf_1.crs)
    info_first = gdf_1["geometry"].value_counts().sum()
    info_second = gdf_2["geometry"].value_counts().sum()
    print(f"The first data has {info_first} lines and the second data has {info_second} lines")

    # Break down MultiLineStrings into LineStrings so that the lines that can iterated individually
    gdf_1 = gdf_1.explode(index_parts=False, ignore_index=True)
    gdf_2= gdf_2.explode(index_parts=False, ignore_index=True)

    # Check for intersecting lines
    gdf_diff = gdf_2[~gdf_2.intersects(gdf_1.unary_union)]
    diff = gdf_diff["geometry"].value_counts().sum()
    print(f"There are {diff} lines from the second data that do not intersect with the first one")

    # Calculate distance and assign values to a field
    gdf_diff = gdf_diff.to_crs(epsg=32631)
    gdf_diff["distance_m"] = gdf_diff.geometry.length

    # ================== PLOT FINAL DIFFERENCE ==================
    # Create a map centered roughly on your data
    m = leafmap.Map(center=[6.45, 3.39], zoom=9, style="streets")

    # Style for non-right-of-way lines
    style_non_right = {
        "color": "blue",
        "weight": 2,
    }

    # Style for right-of-way lines
    style_right = {
        "color": "red",
        "weight": 2,
    }

    # Add the GeoDataFrames
    m.add_gdf(
        gdf_diff,
        layer_type="line",
        layer_name="Non-Right-of-Way Roads",
        style=style_non_right,
    )

    # Add right-of-way roads
    m.add_gdf(
        gdf_1,
        layer_type="line",
        layer_name="Right-of-Way Roads",
        style=style_right,
    )

    # Zoom to fit both datasets
    m.zoom_to_gdf(pd.concat([gdf_diff, gdf_1]))

    return  gdf_diff, m
