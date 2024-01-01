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












































<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>GET NDVI</title>
  <link rel="stylesheet" type="text/css" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
  <h1>NDVI Temporal Profile Download Tool<br>
  Upload a GeoJSON or ZIP or KML File that contains polygons of Interest</h1>
<center>
  <form id="uploadForm" enctype="multipart/form-data">
    <label for="file" class="custom-file-upload1">Select File From Computer</label>
    <input type="file" name="file" id="file" accept=".zip,.geojson,.kml">
    <br>

  </form>
  
  <div id="datasetContainer" style="display:none;">
    
    <div id="uploadMsg" class="upload-msg"></div>    
    <a href="/ndvi_profile_generator" class="file-forma-link" style="
    margin-left: 70%;
    margin-top: 30px;
">Choose File Format</a>
    <br/>
    <label for="dataset">Select Dataset:</label>
    <select id="dataset" name="dataset">
      <option value="sentinel">Sentinel</option>

    </select>

    <br/><br/> 
  
    <button type="button" id="submitDatasetBtn" class="submit-btn">Submit</button>
  </div>

  <div id="processingContainer" style="display:none;">
    <p id="processingMsg"></p>
    <a id="downloadBtn" style="display:none;">Download Data</a>
  </div>
  </center>

  <script src="{{url_for('static',filename='js/custom1.js')}}"></script>
</body>
</html>







var abortController = new AbortController();

document.getElementById('file').addEventListener('change', function () {

  abortController.abort();
  abortController = new AbortController();

  var file = this.files[0];
  var fileType = file.name.split('.').pop().toLowerCase();

  var validExtensions = ['zip', 'geojson', 'kml'];

  if (!validExtensions.includes(fileType)) {
    showErrorMsg('Invalid File Format');
    return;
  }

  document.getElementById('uploadMsg').innerHTML = 'Uploaded: ' + file.name;
  document.getElementById('uploadForm').style.display = 'none';
  document.getElementById('datasetContainer').style.display = 'block';
  document.getElementById('processingContainer').style.display = 'none';
});

document.getElementById('submitDatasetBtn').addEventListener('click', function () {
  document.getElementById('datasetContainer').style.display = 'none';
  document.getElementById('processingContainer').style.display = 'block';
  document.getElementById('processingMsg').innerHTML = 'Processing File...';

  var file = document.getElementById('file').files[0];
  var dataset = document.getElementById('dataset').value;
  var formData = new FormData();
  formData.append('file', file);
  formData.append('dataset', dataset);
  var url = '/process_file';

  fetch(url, {
    method: 'POST',
    body: formData,
    signal: abortController.signal,
  })
    .then((response) => {
      if (response.ok) {
        return response.blob();
      } else {
        return response.text().then((message) => {
          throw new Error(message);
        });
      }
    })
    .then((blob) => {
      var downloadBtn = document.getElementById('downloadBtn');
      var url = window.URL.createObjectURL(blob);
      downloadBtn.style.display = 'block';
      downloadBtn.href = url;
      downloadBtn.download = 'output.csv';
      document.getElementById('processingMsg').innerHTML = 'Process Completed';
    })
    .catch((error) => {
      if (error.name === 'AbortError') {
       
        document.getElementById('processingMsg').innerHTML = 'File processing was aborted.';
      } else {
     
        console.error('Error:', error);
        document.getElementById('processingMsg').innerHTML = 'There was an error occurred during file processing.';
      }
    });
});



function showErrorMsg(msg) {
  var uploadMsg = document.getElementById('uploadMsg');
  uploadMsg.innerHTML = msg;
  uploadMsg.style.color = 'red';
}


window.addEventListener('beforeunload', function () {
  abortController.abort();
});






body {
  font-family: 'Arial', sans-serif;
  background-color: #f7f7f7;
  margin: 0;
  padding: 0;
}

h1, h3 {
  text-align: center;
  color: #3498db;
  margin-top: 5%;
  margin-bottom: 20px;
  padding: 20px;
}

form, #datasetContainer, #processingContainer {
  max-width: 600px;
  margin: 20px auto;
  background: #ffffff;
  padding: 30px;
  margin-top: 40px;
  border-radius: 10px;
  box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
}

.custom-file-upload, #submitDatasetBtn {
  display: inline-block;
  padding: 15px 25px;
  cursor: pointer;
  background-color: #3498db;
  color: #ffffff;
  border: none;
  border-radius: 5px;
  transition: background-color 0.3s ease;
}

.custom-file-upload:hover, #submitDatasetBtn:hover {
  background-color: #2980b9;
}

#file {
  display: none;
}

label[for="file"], label[for="dataset"] {
  margin-right: 10px;
  cursor: pointer;
  color: #333;
}

#dataset, #columnName {
  width: calc(100% - 20px);
  padding: 12px;
  margin-top: 15px;
  box-sizing: border-box;
  border: 1px solid #ccc;
  border-radius: 5px;
}

.upload-msg, #processingMsg {
  margin-top: 15px;
  color: #333;
  margin-left: 10px;
}

.submit-btn {
  background-color: #2ecc71;
  color: #ffffff;
  padding: 15px 25px;
  border: none;
  border-radius: 5px;
  font-weight: bold;
  cursor: pointer;
  transition: background-color 0.3s ease;
}

.submit-btn:hover {
  background-color: #27ae60;
}

#downloadBtn {
  display: none;
  color: #3498db;
  cursor: pointer;
  text-decoration: none;
}

#downloadBtn:hover {
  text-decoration: underline;
}



.custom-file-upload1 {
  background-color: rgb(240, 180, 180);
  display: inline-block;
  padding: 15px 15px;
  cursor: pointer;
  font-weight: bold;
  color: #e6214f;
  border: none;
  border-radius: 5px;
  transition: background-color 0.3s ease;
}
