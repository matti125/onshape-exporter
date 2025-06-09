#! /usr/bin/env python3
# Authenticate with external JSON file.
import requests
import os
import time
import base64
import sys
import argparse
import yaml
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

def log(msg, verbosity=1, level=1):
    if verbosity >= level:
        print(msg)

def log_error(msg):
    sys.stderr.write(f"[{datetime.now().isoformat()}] ERROR: {msg}\n")

class Context:
    def __init__(self, access, secret, ids, verbosity=1):
        self.auth = (access, secret)
        self.ids = ids
        self.verbosity = verbosity

def parse_onshape_path(ids, template):
    return f"https://cad.onshape.com/api{template.format(
        did=ids['did'],
        eid=ids['eid'],
        wv=ids['wvm'],
        wvm=ids['wvm'],
        wvid=ids['wvmid'],
        wvmid=ids['wvmid'],
        wid=ids.get('wid'),
        vid=ids.get('vid'),
        mid=ids.get('mid')
    )}"

def get_onshape_direct(ctx, url, headers=None):
    response = requests.get(
        url,
        auth=ctx.auth,
        headers=headers or {"Accept": "application/json"}
    )
    response.raise_for_status()
    return response

def get_onshape_json(ctx, path_template):
    url = parse_onshape_path(ctx.ids, path_template)
    return get_onshape_direct(ctx, url).json()

def post_onshape_json(ctx, path_template, json_payload):
    url = parse_onshape_path(ctx.ids, path_template)
    response = requests.post(
        url,
        auth=ctx.auth,
        headers={
            "Accept": "application/json;charset=UTF-8; qs=0.09",
            "Content-Type": "application/json"
        },
        json=json_payload
    )
    response.raise_for_status()
    return response.json()

def load_api_keys(path, stack_override=None):
    if path == "-":
        try:
            data = yaml.safe_load(sys.stdin)
            return data['access'], data['secret']
        except yaml.YAMLError as e:
            log_error(f"Failed to parse API key data from stdin: {e}")
            sys.exit(1)
        except KeyError:
            log_error("API key data must contain 'access' and 'secret' fields.")
            sys.exit(1)
    try:
        with open(path) as f:
            config = yaml.safe_load(f)
            default_stack = stack_override or config.get("default_stack")
            if not default_stack:
                log_error("YAML config must include a 'default_stack' key.")
                sys.exit(1)
            profile = config.get(default_stack)
            if not profile:
                log_error(f"Profile '{default_stack}' not found in the config file.")
                sys.exit(1)
            return profile["access_key"], profile["secret_key"]
    except Exception as e:
        log_error(f"Failed to load YAML API key file '{path}': {e}")
        sys.exit(1)



def get_ids(url):
    urlArr = url.split("/")
    dIndex = urlArr.index("documents")
    DID = urlArr[dIndex + 1]
    eIndex = urlArr.index("e")
    EID = urlArr[eIndex + 1]

    WID = VID = MID = None
    if "w" in urlArr:
        WID = urlArr[urlArr.index("w") + 1]
    if "v" in urlArr:
        VID = urlArr[urlArr.index("v") + 1]
    if "m" in urlArr:
        MID = urlArr[urlArr.index("m") + 1]

    if MID:
        WVMID = MID
        WVM = "m"
    elif VID:
        WVMID = VID
        WVM = "v"
    elif WID:
        WVMID = WID
        WVM = "w"
    else:
        raise ValueError("URL must contain 'w', 'v', or 'm'")

    return {
        'did': DID,
        'eid': EID,
        'wid': WID,
        'vid': VID,
        'mid': MID,
        'wvmid': WVMID,
        'wvm': WVM
    }




def get_element_configuration(ctx):
    response = get_onshape_json(ctx, "/elements/d/{did}/{wvm}/{wvmid}/e/{eid}/configuration")
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
    response = get_onshape_json(ctx, f"/parts/d/{{did}}/{{wvm}}/{{wvmid}}/e/{{eid}}?{queryParam}")
    part_names = [part['name'] for part in response]
    for part in response:
        if part['name'] == partToExport:
            return part['partId']
    raise ValueError(f"Part named '{partToExport}' not found in the Part Studio.")


def encode_configuration_url(ctx, os_config_parameters):
    response = post_onshape_json(ctx, "/elements/d/{did}/e/{eid}/configurationencodings",
                                 {"parameters": os_config_parameters})
    encodedId = response['encodedId']
    queryParam = response['queryParam']
    return encodedId, queryParam


def create_translation_request(ctx, encodedId, PID, formatName="STEP"):
    return post_onshape_json(
        ctx,
        "/partstudios/d/{did}/{wv}/{wvid}/e/{eid}/translations",
        {
            "configuration": encodedId,
            "formatName": formatName,
            "partIds": PID,
            "storeInDocument": False
        }
    )['id']


def wait_for_translation_request(ctx, TID):
    while True:
        time.sleep(5)
        response = get_onshape_json(ctx, f"/translations/{TID}")
        log("Translation status: " + response["requestState"], verbosity=ctx.verbosity, level=2)
        if response["requestState"] == "DONE":
            break
    return response


def download_external_data(ctx, FID, filename="result.step"):
    url = f"https://cad.onshape.com/api/documents/d/{ctx.ids['did']}/externaldata/{FID}"
    response = get_onshape_direct(ctx, url, headers={
        "Accept": "application/octet-stream",
        "Content-Type": "application/json"
    })
    with open(filename, 'wb') as f:
        f.write(response.content)



def load_config_with_fallback(filename="onshape-exporter.conf"):
    if filename == "-":
        try:
            return yaml.safe_load(sys.stdin)
        except yaml.YAMLError as e:
            log_error(f"Failed to parse configuration from stdin: {e}")
            sys.exit(1)
    if not os.path.exists(filename):
        log_error(f"Configuration file '{filename}' not found in current directory.")
        sys.exit(1)
    with open(filename) as f:
        return yaml.safe_load(f)
    
def get_version_name(ctx):
    try:
        #only return a name if we have a "genuine" version, and not a microversion
        if not ctx.ids['wvm'] == "v":
            return None
        vid = ctx.ids.get("vid")
        version_info_list = get_onshape_json(ctx, "/documents/d/{did}/versions")
        version_entry = next((v for v in version_info_list if v["id"] == vid), None)
        if not version_entry:
            raise ValueError(f"Error generating the filename suffix. Version ID '{vid}' not found in the version list.")
        return version_entry["name"]
    except Exception as e:
        log_error(e)
        return None

def generate_file_suffix(ctx):
    suffix = ""
    if ctx.ids['wvm'] == "v":
        suffix += get_version_name(ctx)
    else:
        suffix += "wip"
    return suffix

def export_configuration(ctx, export, partName, config_schema, formatName, suffix):
    try:
#        log(f"Exporting configuration: {export.get('name', '?')}", verbosity=ctx.verbosity, level=1)
        log(f"Exporting config: {export}", verbosity=ctx.verbosity, level=1)
        #resolve the GUI-visible names to the ids used internally in os
        resolved_params = resolve_configuration_parameters(export["config"], config_schema)
        log(f"Resolved parameters: {resolved_params}", verbosity=ctx.verbosity, level=2)
        #encode the resolved parameters so that they can be transported in GET and PUT requests
        encodedId, queryParam = encode_configuration_url(ctx, resolved_params)
        log(f"Encoded ID: {encodedId}", verbosity=ctx.verbosity, level=2)
        log(f"Query Param: {queryParam}", verbosity=ctx.verbosity, level=2)
        #find the internal name of the GUI-visible part name
        PID = get_part_id(ctx, partName, queryParam=queryParam)
        log(f"Part ID: {PID}", verbosity=ctx.verbosity, level=2)
        #start translation
        TID = create_translation_request(ctx, encodedId, PID, formatName=formatName)
        #poll until ready
        status = wait_for_translation_request(ctx, TID)
        FID = status['resultExternalDataIds'][0]
        filename = f"{partName}-{export['name']}-{suffix}.{formatName.lower()}"
        download_external_data(ctx, FID, filename=filename)
        log(f"Downloaded {filename}", verbosity=ctx.verbosity, level=1)
    except Exception as e:
        log_error(f"Failed to export configuration '{export.get('name', '?')}': {e}")

def main():
    parser = argparse.ArgumentParser(description="Export Onshape configurations")
    parser.add_argument("--config", help="Path to configuration file", default="onshape-exporter.conf")
    parser.add_argument("--keyfile", help="Path to Onshape API key file", default=os.path.expanduser("~/.onshape_client_config.yaml"))
    parser.add_argument("--url", help="Override the URL in config")
    parser.add_argument("--part", help="Override the part name in config")
    parser.add_argument("--profile", help="Override default_stack in API key config")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--quiet", action="store_true", help="Suppress all output except errors")
    args = parser.parse_args()

    API_ACCESS, API_SECRET = load_api_keys(args.keyfile, stack_override=args.profile)
    config_data = load_config_with_fallback(args.config)

    if "formats" not in config_data or not isinstance(config_data["formats"], list) or not config_data["formats"]:
        log_error("The configuration file must include a non-empty 'formats' list.")
        sys.exit(1)
    if "parts" not in config_data or not isinstance(config_data["parts"], list) or not config_data["parts"]:
        log_error("The configuration file must include a non-empty 'parts' list.")
        sys.exit(1)

    if args.url:
        config_data["url"] = args.url
    if args.part:
        config_data["part"] = args.part

    # read the config file
    formats = config_data["formats"]
    parts = config_data["parts"]
    configurationsToExport = config_data.get("configurationsToExport", [])

    # Determine verbosity level
    if args.quiet:
        verbosity = 0
    elif args.verbose:
        verbosity = 2
    else:
        verbosity = 1


    # the context include authentication and the document id, version/workspace/microversion IDs
    ctx = Context(API_ACCESS, API_SECRET, get_ids(config_data["url"]), verbosity=verbosity)

    suffix = generate_file_suffix(ctx)

    # get the onshape-internal configuration schema values that API will mostly use 
    # instead of the GUI-visible names
    config_schema = get_element_configuration(ctx)

    # Validate all configurations first
    for export in configurationsToExport:
        try:
            resolve_configuration_parameters(export["config"], config_schema)
        except ValueError as e:
            log_error(f"Configuration '{export.get('name', '?')}' is invalid: {e}")
            return

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for formatName in formats:
            for partName in parts:
                for export in configurationsToExport:
                    futures.append(executor.submit(export_configuration, ctx, export, partName, config_schema, formatName, suffix))
        for future in as_completed(futures):
            future.result()


if __name__ == "__main__":
    main()
