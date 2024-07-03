import os
from json import loads, dumps
import csv

# for local testing
try:
    private = '/web/groups/' + os.environ['USER'] + '/private/queup/'
except:
    private = os.environ['CONTEXT_DOCUMENT_ROOT'].replace('public_html', 'private') + 'queup/'

def sectiondata(room, data="", action="get"):
    if not os.path.exists(private + '/sections'):
        os.mkdir(private + '/sections')
    if action == "get":
        if not os.path.exists(private + '/sections/' + room + '.json'):
            return ""
        with open(private + '/sections/' + room + '.json') as f:
            # convert JSON to CSV
            data = loads(f.read())
            keys = list(data.keys())
            vals = list(data.values())
            data = [",".join([keys[i], vals[i]]) for i in range(len(keys))]
            data = "\n".join(["username,section"] + data)
            return data
    elif action == "set" and data != "":
        # convert CSV to JSON
        data = data.lower()
        if not data.startswith("username"):
            data = "username,section\n" + data
        data = list(csv.DictReader(data.split("\n")))
        data = {x["username"]: x["section"] for x in data}
        with open(private + '/sections/' + room + '.json', 'w') as f:
            f.write(dumps(data))
        return True
    elif action == "set":
        return False
    else:
        return False

def getsections(room):
    if not os.path.exists(private + "sections/" + room + ".json"):
        return {}
    with open(private + "sections/" + room + ".json", "r") as f:
        sections = loads(f.read())
    return sections

def getdblog(room):
    with open(private + "logs/" + room + ".log") as f:
        data = [x.split(",") for x in f.read().split("\n") if room in x]
    # splice in section data
    sections = getsections(room)
    for i in range(len(data)):
        if data[i][1] in sections:
            data[i].insert(2, sections[data[i][1]])
        else:
            data[i].insert(2, "")
    return data