import requests
import json
import base64


def decode_base64_with_padding(encoded: str) -> str:
    padding_needed = (-len(encoded)) % 4  # base64 requires length % 4 == 0
    encoded += "=" * padding_needed
    return base64.urlsafe_b64decode(encoded).decode("utf-8")


with open("APIKey.json") as f: # Change file name if needed
   data = json.load(f)
   API_ACCESS = data['access']
   API_SECRET = data['secret']


URL = "https://cad.onshape.com/documents/f4cea9fb4db59f7a3d2d509f/v/82d7d44f67371cc929537893/e/662b472dccfbb4adb6039290"

def getIds(url, wv):
  urlArr = url.split("/")
  dIndex = urlArr.index("documents")
  DID = urlArr[dIndex+1]
  eIndex = urlArr.index("e")
  EID = urlArr[eIndex+1]
  wvIndex = urlArr.index(wv)
  WVID = urlArr[wvIndex+1]

  return DID, EID, WVID

DID, EID, WID = getIds(URL, "v")

response = requests.post(
    # Use one of the two API endpoints (Part Studio vs. Assembly)
    "https://cad.onshape.com/api/elements/d/{}/e/{}/configurationencodings".format(
        DID, EID
    ),
    auth=(API_ACCESS, API_SECRET),
    headers={
        "Accept": "application/json;charset=UTF-8; qs=0.09",
        "Content-Type": "application/json"
    },
    json={
        "parameters": [
          {
            "parameterId": "cone",
            "parameterValue": "false"
          }
        ]
      }
)
encodedId = response.json()['encodedId']


#@scp=string;cone=false
#encodedId = "JTQwc2NwPXN0cmluZztjb25lPWZhbHNl"
#true:
#encodedId = "JTQwc2NwPXN0cmluZztjb25lPXRydWU"
#cone=false
#encodedId = "Y29uZT1mYWxzZQ"
#cone=true
#encodedId = "Y29uZT10cnVl"

print(response.text)
print (encodedId)
#print(decode_base64_with_padding(encodedId))

response = requests.post(    
    f"https://cad.onshape.com/api/partstudios/d/{DID}/v/{WID}/e/{EID}/translations",
    auth=(API_ACCESS, API_SECRET),
    headers={
        "Accept": "application/json;charset=UTF-8; qs=0.09",
        "Content-Type": "application/json"
    },
    json={
        "configuration": encodedId, 
        "formatName": "STL",  # Use the "name" of the translation format from above
        "partIds" : "JID",
        "storeInDocument": False
    }
)
print(response.text)