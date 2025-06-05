#! /usr/bin/env python3
# Authenticate with external JSON file.
import json
import requests
import os
import time
import base64
import sys
import argparse
from urllib.parse import quote


class Context:
    def __init__(self, access, secret, ids):
        self.auth = (access, secret)
        self.ids = ids


def load_api_keys(path):
    with open(path) as f:  # Change file name if needed
        data = json.load(f)
        return data['access'], data['secret']



def get_ids(url):
    urlArr = url.split("/")
    dIndex = urlArr.index("documents")
    DID = urlArr[dIndex + 1]
    eIndex = urlArr.index("e")
    EID = urlArr[eIndex + 1]

    MID = None
    if "m" in urlArr:
        mIndex = urlArr.index("m")
        MID = urlArr[mIndex + 1]

    VWID = None
    if "v" in urlArr:
        idx = urlArr.index("v")
        VWID = urlArr[idx + 1]
    elif "w" in urlArr:
        idx = urlArr.index("w")
        VWID = urlArr[idx + 1]
    else:
        raise ValueError("URL must contain either a 'w' (workspace) or 'v' (version)")

    return {
        'did': DID,
        'eid': EID,
        'vwid': VWID,
        'mid': MID,
        'wvm': 'm' if MID else ('v' if 'v' in urlArr else 'w')
    }


def parse_onshape_path(ids, template):
    # ids is a dict with keys: did, eid, wvid, wvm (optional)
    # wvm is the workspace/microversion part like "w/12345" or "m/67890"
    # wvid is the ID without prefix
    # did and eid are document and element IDs
    # template is a string with placeholders {did}, {eid}, {wvid}, {wvm}
    return f"https://cad.onshape.com/api{template.format(did=ids['did'], eid=ids['eid'], wvid=ids['vwid'], wvm=ids['wvm'])}"


def get_element_configuration(ctx):
    url = parse_onshape_path(ctx.ids, "/elements/d/{did}/{wvm}/{wvid}/e/{eid}/configuration")
    response = requests.get(
        url,
        auth=ctx.auth,
        headers={"Accept": "application/json"}
    )
    response = response.json()
    #get the config in a format that has the UI-visible name as key and the "message" as value
    config_schema = {p["message"]["parameterName"]: p for p in response["configurationParameters"]}
    return config_schema


def resolve_configuration_parameters(config, config_schema):
    #Convert UI values into internal identifiers. "config" is a json formatted representation of the UI-visible
    #configuration values:
    # {
    #   "name": "foobar",
    #   "config": {
    #     "Slots X": 3,
    #     "Bin height": "15",
    #     "Slots Y": 4,
    #     "scoop": false,
    #     "labelWidth": 13,
    #     "Top wall enforcement": true                
    # }

    resolved_params = []
    for conf_param_name, conf_value in config.items():
        # check that the UI -visible name is in the schema a key
        if conf_param_name not in config_schema:
            raise ValueError(f"Unknown configuration parameter: '{conf_param_name}'")

        conf_param_def = config_schema[conf_param_name]["message"]
        param_id = conf_param_def["parameterId"]
        conf_param_type = config_schema[conf_param_name].get("typeName")
 
        if conf_param_type == "BTMConfigurationParameterEnum":
            valid_options = {opt["message"]["optionName"]: opt["message"]["option"] for opt in conf_param_def["options"]}
            if conf_value not in valid_options:
                raise ValueError(f"Invalid value '{conf_value}' for enum '{conf_param_name}'. Valid options: {list(valid_options.keys())}")
            resolved_value = valid_options[conf_value]

        elif conf_param_type == "BTMConfigurationParameterQuantity":
            range_info = conf_param_def.get("rangeAndDefault", {}).get("message", {})
            min_val = range_info.get("minValue")
            max_val = range_info.get("maxValue")
            unit_raw = range_info.get("units")
            default_unit = f" {unit_raw}" if unit_raw else ""
            
            if isinstance(conf_value, str):
                if not any(conf_value.endswith(unit) for unit in (" mm", "cm", "in", "m", "ft")):
                    raise ValueError(f"Value '{conf_value}' for quantity '{conf_param_name}' must end with a supported unit")
                try:
                    numeric_value = float(conf_value.split()[0])
                except ValueError:
                    raise ValueError(f"Could not parse numeric part from quantity '{conf_value}'")
                resolved_value = conf_value
            elif isinstance(conf_value, (int, float)):
                numeric_value = conf_value
                resolved_value = f"{conf_value}{default_unit}"
            else:
                raise ValueError(f"Value '{conf_value}' for quantity '{conf_param_name}' must be a number or string with units")

            if min_val is not None and numeric_value < float(min_val):
                raise ValueError(f"Value {conf_value} for '{conf_param_name}' is below minimum {min_val}")
            if max_val is not None and numeric_value > float(max_val):
                raise ValueError(f"Value {conf_value} for '{conf_param_name}' exceeds maximum {max_val}")

        elif conf_param_type == "BTMConfigurationParameterBoolean":
            if not isinstance(conf_value, bool):
                raise ValueError(f"Value for boolean '{conf_param_name}' must be true or false")
            resolved_value = conf_value

        else:
            raise ValueError(f"Unsupported parameter type '{conf_param_type}' for parameter '{conf_param_name}'")

        resolved_params.append({
            "parameterId": param_id,
            "parameterValue": resolved_value
        })

    return resolved_params


def get_part_id(ctx, partToExport, queryParam):
    url = parse_onshape_path(ctx.ids, "/parts/d/{did}/{wvm}/{wvid}/e/{eid}") + f"?{queryParam}"
    response = requests.get(
        url,
        auth=ctx.auth,
        headers={
            "Accept": "application/json"
        }
    )
    response = response.json()
    part_names = [part['name'] for part in response]
    # print("Available parts:", part_names)
    for part in response:
        if part['name'] == partToExport:
            return part['partId']
    raise ValueError(f"Part named '{partToExport}' not found in the Part Studio.")


def encode_configuration_url(ctx, os_config_parameters):
    url = parse_onshape_path(ctx.ids, "/elements/d/{did}/e/{eid}/configurationencodings")
    response = requests.post(
        url,
        auth=ctx.auth,
        headers={
            "Accept": "application/json;charset=UTF-8; qs=0.09",
            "Content-Type": "application/json"
        },
        json={
            "parameters": os_config_parameters
        }
    )
    encodedId = response.json()['encodedId']
    queryParam = response.json()['queryParam']
    # print(response.text)

    
    return encodedId, queryParam


def create_translation_request(ctx, encodedId, PID, formatName="STEP"):
    url = parse_onshape_path(ctx.ids, "/partstudios/d/{did}/{wvm}/{wvid}/e/{eid}/translations")

    response = requests.post(
        url,
        auth=ctx.auth,
        headers={
            "Accept": "application/json;charset=UTF-8; qs=0.09",
            "Content-Type": "application/json"
        },
        json={
            "configuration": encodedId,
            "formatName": formatName,
            "partIds": PID,
            "storeInDocument": False
        }
    )
    response.raise_for_status()
    return response.json()['id']


def wait_for_translation_request(ctx, TID):
    while True:
        response = requests.get(
            f"https://cad.onshape.com/api/translations/{TID}",
            auth=ctx.auth,
            headers={
                "Accept": "application/json;charset=UTF-8; qs=0.09",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        translation_status = response.json()
        print("Translation status:", translation_status["requestState"])
        if translation_status["requestState"] == "DONE":
            break
        time.sleep(2)
    return translation_status


def download_external_data(ctx, FID, filename="result.step"):
    url = f"https://cad.onshape.com/api/documents/d/{ctx.ids['did']}/externaldata/{FID}"
    response = requests.get(
        url,
        auth=ctx.auth,
        headers={
            "Accept": "application/octet-stream",
            "Content-Type": "application/json"
        }
    )
    with open(filename, 'wb') as f:
        f.write(response.content)

def load_config_with_fallback(filename="onshape-exporter.conf"):
    if not os.path.exists(filename):
        print(f"Configuration file '{filename}' not found in current directory.")
        sys.exit(1)
    with open(filename) as f:
        return json.load(f)
    
def get_version_name(ctx):
    url = parse_onshape_path(ctx.ids, "/documents/d/{did}/versions")
    response = requests.get(url, auth=ctx.auth, headers={"Accept": "application/json"})
    if response.status_code == 200:
        version_info_list = response.json()
        version_entry = next((v for v in version_info_list if v["id"] == ctx.ids["vwid"]), None)
        return version_entry["name"] if version_entry else ctx.ids["vwid"]
    else:
        print(response.text)
        return ctx.ids["vwid"]

def generate_file_suffix(ctx):
    suffix = ""
    if ctx.ids['wvm'] == "v":
        suffix += get_version_name(ctx)
    else:
        suffix += "wip"

    if ctx.ids['wvm'] == "m":
        shortid = ctx.ids['mid'][:8]
        suffix += f"-m-{shortid}"
    return suffix

def main():
    parser = argparse.ArgumentParser(description="Export Onshape configurations")
    parser.add_argument("--config", help="Path to configuration file", default="onshape-exporter.conf")
    parser.add_argument("--keyfile", help="Path to Onshape API key file", default=os.path.expanduser("~/Onshape-test-APIKey.json"))
    parser.add_argument("--url", help="Override the URL in config")
    parser.add_argument("--part", help="Override the part name in config")
    args = parser.parse_args()

    API_ACCESS, API_SECRET = load_api_keys(args.keyfile)
    config_data = load_config_with_fallback(args.config)

    if args.url:
        config_data["url"] = args.url
    if args.part:
        config_data["part"] = args.part

    # read the config file
    formatName = config_data.get("format", "STEP")
    partName = config_data.get("part", "Part 1")
    configurationsToExport = config_data.get("configurationsToExport", [])

    # the context include authentication and the document id, version/workspace/microversion IDs
    ctx = Context(API_ACCESS, API_SECRET, get_ids(config_data["url"]))

    suffix = generate_file_suffix(ctx)

    # get the onshape-internal configuration schema values that API will mostly use 
    # instead of the GUI-visible names
    config_schema = get_element_configuration(ctx)

    # Validate all configurations first
    for export in configurationsToExport:
        try:
            resolve_configuration_parameters(export["config"], config_schema)
        except ValueError as e:
            print(f"Configuration '{export.get('name', '?')}' is invalid: {e}")
            return

    # export each product configuration specified in the conf file
    for export in configurationsToExport:
        print(json.dumps(export))
        #map parameters from GUI values to onshape-internally used items
        resolved_params = resolve_configuration_parameters(export["config"], config_schema)
        #Encode the parameters so that the configuration can be used in POST or GET operations to the API
        encodedId, queryParam = encode_configuration_url(ctx, resolved_params)
        #find the internal part Id. Pass the element configuration as well with queryParam, as that can change the internal names
        PID = get_part_id(ctx, partName, queryParam=queryParam)
        #start the translation
        TID = create_translation_request(ctx, encodedId, PID, formatName=formatName)
        # poll until translation ready
        translation_status = wait_for_translation_request(ctx, TID)

        FID = translation_status['resultExternalDataIds'][0]

        filename = f"{partName}-{export['name']}-{suffix}.{formatName.lower()}"
        download_external_data(ctx, FID, filename=filename)


if __name__ == "__main__":
    main()

