import requests
import json
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
            "parameterValue": "true"
          }
        ],
        "standardContentParametersId": "string"
      }
)

encodedId = response.json()['encodedId']
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