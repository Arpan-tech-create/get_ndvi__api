from flask import Flask, render_template, request, send_file,after_this_request,copy_current_request_context
import geopandas as gpd
import json
from io import BytesIO
from datetime import datetime
import pandas as pd
import requests
import os
from tqdm import tqdm
import zipfile
import pandas as pd
import tempfile
import shutil
import xml.etree.ElementTree as ET
from lxml import etree
from shapely.geometry import Polygon
from fastkml import kml

app = Flask(__name__, template_folder='templates')

def process_file(uploaded_file):
    if uploaded_file.filename.endswith('.zip'):
        return process_zip(uploaded_file)
    elif uploaded_file.filename.endswith('.geojson'):
        return process_geojson(uploaded_file)
    elif uploaded_file.filename.endswith('.kml'):
        return process_kml(uploaded_file)
    else:
        return "Unsupported file format. Please upload a zip file, GeoJSON file, or KML file.", 400

def process_zip(uploaded_file):
    zip_content = BytesIO(uploaded_file.read())

    with zipfile.ZipFile(zip_content, 'r') as zip_ref:
        temp_dir = tempfile.mkdtemp()
        zip_ref.extractall(temp_dir)

        shapefile_paths = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    shapefile_paths.append(os.path.join(root, file))

        if shapefile_paths:
            shapefile_path = shapefile_paths[0] 
            gdf = gpd.read_file(shapefile_path)
            gdf = gdf.to_crs('EPSG:4326')
            return process_data(gdf, temp_dir)
        else:
            shutil.rmtree(temp_dir)
            return "No shapefile found in the uploaded zip file.", 400

def process_geojson(uploaded_file):
    geojson_data = json.loads(uploaded_file.read())
    gdf = gpd.GeoDataFrame.from_features(geojson_data['features'])
    return process_data(gdf)

def process_kml(uploaded_file):
    features_data = extract_features_from_kml(uploaded_file)
    gdf = gpd.GeoDataFrame(features_data, geometry='geometry')
    print(gdf)
    return process_data(gdf)

def extract_features_from_kml(uploaded_file):
    features = []
    kml_content = uploaded_file.read()
    print(kml_content)

    try:
        tree = ET.ElementTree(ET.fromstring(kml_content))
        root = tree.getroot()

        for placemark in root.findall('.//{http://www.opengis.net/kml/2.2}Placemark'):
            name_element = placemark.find('.//{http://www.opengis.net/kml/2.2}name')
            coordinates_element = placemark.find('.//{http://www.opengis.net/kml/2.2}coordinates')

            if name_element is not None and coordinates_element is not None:
                name = name_element.text.strip()
                coordinates_str = coordinates_element.text.strip()
                coordinates = [tuple(map(float, coord.split(','))) for coord in coordinates_str.split()]

                feature_data = {'name': name, 'geometry': Polygon(coordinates)}

                schema_data = placemark.find('.//{http://www.opengis.net/kml/2.2}SchemaData')
                print(schema_data)
                if schema_data is not None:
                    for simple_data in schema_data.findall('.//{http://www.opengis.net/kml/2.2}SimpleData'):
                        feature_data[simple_data.attrib['name']] = simple_data.text.strip()

                features.append(feature_data)
               

    except Exception as e:
        return f"Error parsing KML: {str(e)}", 400

    return features
def process_data(gdf, temp_dir=None):
    results = []

    try:
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp()

        for idx, row in tqdm(gdf.iterrows(), total=len(gdf)):
            coordinates = list(row['geometry'].exterior.coords)

            geojson_string = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [coordinates]
                        },
                        "properties": None
                    }
                ]
            }

            payload = json.dumps({
                'dset': 'NDVI_10D_S2_GUJ',
                'geojsonstring': json.dumps(geojson_string),
            })

            try:
                response = requests.post('http://192.168.2.64:55567/run_field_profile', 
                                        data=payload, timeout=90, verify=False, 
                                        headers={'Content-Type': 'application/json'})  
                data = response.json()

                if isinstance(data, list):
                    result = {col: row[col] for col in row.index if col != 'geometry'}
                    for entry in data:
                        timestamp_mill = entry[0]
                        timestamp = datetime.utcfromtimestamp(timestamp_mill / 1000).strftime('%d-%m-%Y')
                        ndvi = entry[1] / 250

                        result[f"{timestamp}_NDVI"] = ndvi

                    results.append(result)
                else:
                    print(f"Invalid response format from server: {data}")

            except requests.exceptions.HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"An error occurred: {err}")

        output_csv_path = os.path.join(temp_dir, 'output.csv')

        csv_df = pd.DataFrame(results)

        csv_df.to_csv(output_csv_path)

        @after_this_request
        @copy_current_request_context
        def cleanup(response):
            if temp_dir:
                with open(output_csv_path, 'rb') as file:
                    response.direct_passthrough = False
                    response.data = file.read()

                shutil.rmtree(temp_dir)

            return response

        return send_file(output_csv_path, as_attachment=True, download_name='output.csv')

    except Exception as e:
        return f"Error processing data: {str(e)}", 500

@app.route('/ndvi_profile_generator')
def index():
    return render_template('new.html')

@app.route('/process_file', methods=['POST'])
def process_file_route():
    uploaded_file = request.files['file']


    if uploaded_file.filename != '':
        return process_file(uploaded_file)
    else:
        return "No file uploaded.", 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
