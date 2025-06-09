#!/usr/bin/env python3
import yaml
from itertools import product

url = """

https://cad.onshape.com/documents/197e41b6f637a60f25779e61/v/f698a28fa3dc96a47d02c87f/e/7136c4d63891688363cc13e2

""".strip()

parts = ["clip"]
formats = ["STEP", "STL"]
formats = ["STL"]
# Input ranges
stackable = [True, False]
#addheight = list(range(1, 26))
addheight = [0,1,8]
addheight = [0]


# Header for the export configuration
export_data = {
    "url": url,
    "parts": parts,
    "formats": formats,
    "configurationsToExport": []
}

# Generate configurations
for stack, aheight in product(stackable,addheight):
    name=str(aheight)
    addHeightBoolean = True
    if stack:
        name+="-stackable"
    # the minimum reasonable add height for stackable is 7mm
    if stack and aheight<7:
        continue

    # Need to set a boolean to cope with zero change
    addHeightBoolean = aheight != 0
    #the minimu allowable per configuration checks.
    # Note that it does not matter if addHeightBooleas is false
    aheight=max(1,aheight)
    config = {
        "name": name,
        "config": {
            "Add Height": addHeightBoolean,
            "Additional Height": f"{aheight} mm",
            "Stackable": stack
        }
    }
    export_data["configurationsToExport"].append(config)

print(yaml.dump(export_data, sort_keys=False))