import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString
# import  matplotlib.pyplot as plt
# import contextily as ctx
from pyproj import Geod
import networkx as nx
import osmnx as ox
import leafmap.foliumap as leafmap

api_key = os.getenv("maptiler_api_key")
style = {
        "color": "red",  # line/border color
        "weight": 2,  # line width
        "fillColor": "#3388ff",  # fill color (for polygons)
        "fillOpacity": 0.8,
    }

def wrangle_data(data):
    """
    :param: dataset that contains Street name, Coordinates of the lines
    :return: a cleaned dataset
    """
    df = pd.read_csv(data)
    print("Removing a bad row")
    df = df[df["Unnamed: 5"] != "DISTANCE (M)"]
    print("Removing more bad rows and renaming some columns")
    df = df.iloc[2:].reset_index(drop=True)
    df = df.rename(
        columns={
            "AREA/ \nNEIGHBOURHOOD": "Area",
            "ROAD/STREET NAME": "road_street_name",
            "Unnamed: 5": "distance(m)",
            "Unnamed: 6": "road_ownership",
            "GPS Coordinates of road": "start_north",
            "Unnamed: 8": "start_east",
            "Unnamed: 9": "end_north",
            "Unnamed: 10": "end_east",
        }
    )

    # print(f"Sample of corrected data\n{df.head(10)}")
    cols_to_convert = ["distance(m)", "start_east", "end_east", "start_north", "end_north"]

    # --- helper to clean messy numbers ---
    def clean_numeric_string(s):
        if pd.isna(s):
            return s
        s = str(s).strip()  # trim spaces
        s = s.replace(" ", "")  # remove internal spaces
        s = s.replace(",", ".")  # replace commas with dots

        # if more than one dot → keep the first as decimal separator
        if s.count(".") > 1:
            first, *rest = s.split(".")
            s = first + "." + "".join(rest)

        # remove leading dots like ".3.3814"
        if s.startswith("."):
            s = s[1:]

        return s

    for col in cols_to_convert:
        df[col] = df[col].apply(clean_numeric_string)

    df[cols_to_convert] = df[cols_to_convert].astype(float)

    df["geometry"] = [
        LineString([(x1, y1), (x2, y2)])
        for x1, y1, x2, y2 in zip(
            df["start_east"], df["start_north"], df["end_east"], df["end_north"]
        )
    ]
    return df

def convert_to_gdf_and_plot(data):
    """
    :param data: cleaned dataset from wrangle_data()
    :return: geospatial dataset
    """
    print("Plotting the roads")
    gdf_bad_lines = gpd.GeoDataFrame(data, geometry="geometry", crs="EPSG:4326")
    m = leafmap.Map(center=[3.3984, 6.4509], zoom=3, style="streets")

    # Add GDF with tooltip
    tooltip_fields = [col for col in ["road_street_name", "LOCAL GOVERNMENT", "distance(m)"] if col in gdf_bad_lines.columns]
    m.add_gdf(
        gdf_bad_lines, layer_type="fill", layer_name="Roads",
        style=style, tooltip=tooltip_fields, info_mode="on_hover"
    )
    m.zoom_to_gdf(gdf_bad_lines)
    return m

def load_graph(place="Lagos, Nigeria", network_type="all"):
    """
    download roads location in the  of interest
    :param place: location of interest
    :param network_type: whether you want "drive"(able) roads, "walk"able roads, or "all" roads
    :return: the downloaded roads of the location of interest
    """
    print(f"Downloading street data for {place}...")
    g = ox.graph_from_place(place, network_type=network_type)
    print("Graph download complete!")
    return g

# Function to fix a single row
def correct_erroneous_line(row, g):
    """
    extract start/end coords
    snap to nearest OSM nodes
    compute shortest path
    return LineString or None
    :param row: the rows of the coordinates
    :param g: the downloaded roads from load_graph()
    :return:
    """
    geod = Geod(ellps="WGS84")

    try:
        # Extract coordinates
        print("Extracting Coordinates...")
        startLatLon = (row["start_north"], row["start_east"])  # (lat, lon)
        endLatLon = (row["end_north"], row["end_east"])

        # Check for NaN
        if pd.isna(startLatLon[0]) or pd.isna(startLatLon[1]) or pd.isna(endLatLon[0]) or pd.isna(endLatLon[1]):
            return None

        # Find nearest nodes (lon, lat order!)
        orig_node = ox.distance.nearest_nodes(g, X=startLatLon[1], Y=startLatLon[0])
        dest_node = ox.distance.nearest_nodes(g, X=endLatLon[1], Y=endLatLon[0])

        # Compute geodesic distance between snapped nodes
        orig_coords = (g.nodes[orig_node]["y"], g.nodes[orig_node]["x"])
        dest_coords = (g.nodes[dest_node]["y"], g.nodes[dest_node]["x"])
        distance_m = geod.inv(orig_coords[1], orig_coords[0],
                              dest_coords[1], dest_coords[0])[2]

        if distance_m == 0.0000:
            return None  # same node, no line needed

        # Compute shortest path
        print("Computing shortest path...")
        route = nx.shortest_path(g, orig_node, dest_node, weight="length")

        if len(route) < 2:
            return None

        # Convert to LineString
        print("Converting to LineStrings")
        return LineString([(g.nodes[n]['x'], g.nodes[n]['y']) for n in route])

    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    except Exception as e:
        print(f"Routing error for row {row.name}: {e}")
        return None


# Wrapper for a whole DataFrame
def correct_lines_in_dataframe(data, g):
    """
    :param data: fixed data from wrangle_data()
    :param g: from load_graph()
    :return: cleaned data that has the corrected lines
    """
    print("Correcting erroneous lines...")
    data["geometry"] = data.apply(lambda row: correct_erroneous_line(row, g), axis=1)
    successful_routes = data["geometry"].notna().sum()
    print(f"Successfully routed: {successful_routes}/{len(data)}")
    return data

def plot_corrected_lines(data):
    """
    Plot the corrected geometries
    :param data: fixed data from wrangle_data()
    :return: a plot of the loines
    """

    gdf = gpd.GeoDataFrame(data, geometry="geometry", crs="EPSG:4326")
    m = leafmap.Map(center=[3.3984, 6.4509], zoom=4, style="streets")
    # Add GDF with tooltip
    tooltip_fields = [col for col in ["road_street_name", "LOCAL GOVERNMENT", "distance(m)"] if col in gdf.columns]
    m.add_gdf(
        gdf, layer_type="fill", layer_name="Roads", style=style, tooltip=tooltip_fields, info_mode="on_hover"
    )
    m.zoom_to_gdf(gdf)
    return m















