#! /usr/bin/env python3
import os, sys, re
from json import dumps, loads
import csv
import pyinotify
import sqlite3

from functools import reduce
from urllib.parse import parse_qs

ROOM_RGX = r'^[A-Z0-9]{5}$'

class DBConnection:
    def __init__(self, room_db):
        self.conn = sqlite3.connect(room_db)
        self.cur = self.conn.cursor()
    def __enter__(self):
        return [self.conn, self.cur]
    def __exit__(self, type, value, traceback):
        self.conn.commit()
        self.conn.close()

def getowners(room_db, room):
    if not os.path.exists(room_db):
        return []
    if not re.match(ROOM_RGX, room):
        raise Exception("getowners: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        allusers = list(cur.execute("SELECT owners FROM room{0}".format(room)))
        if len(allusers) == 0:
            return []
        allusers = allusers[0]
        allusers = allusers[0].split(",")
        return allusers

def sectiondata(room_db, room, data="", action="get"):
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

try:
    private = os.environ['DOCUMENT_ROOT'] + os.environ['CONTEXT_PREFIX'] + '/private/queup/'
except KeyError:
    # for local testing
    private = os.environ['HOME'] + '/private/queup/'
    private = private.replace('local/a/ece270dv', 'web/groups/ece270dev')

def getdblog(room):
    with open(private + "room.log") as f:
        data = [x.split(",") for x in f.read().split("\n") if room in x]
    # splice in section data
    sections = getsections(room)
    for i in range(len(data)):
        if data[i][1] in sections:
            data[i].insert(2, sections[data[i][1]])
        else:
            data[i].insert(2, "")
    return data

######################
# WSGI quick return
######################
def ret_ok(sr, body=""):
    # body = b'Hello world!\n'
    enc = body.encode()
    sr('200 OK', [('content-type', 'text/plain')])
    return [enc]

def ret_json(sr, body):
    enc = body.encode()
    sr('200 OK', [('Content-Type', 'text/plain'), ('Content-Length', str(len(enc)))])
    return [enc]

def ret_400(sr, body=""):
    enc = body.encode()
    sr('400 Bad Request', [('content-type', 'text/plain')])
    # sys.stderr.write("400 Bad Request: " + body + "\n")
    return [enc]

def ret_401(sr, body=""):
    enc = body.encode()
    sr('401 Unauthorized', [('content-type', 'text/plain')])
    return [enc]

def ret_403(sr, body=""):
    enc = body.encode()
    sr('403 Forbidden', [('content-type', 'text/plain')])
    return [enc]

def ret_404(sr, body=""):
    enc = body.encode()
    sr('404 Not Found', [('content-type', 'text/plain')])
    return [enc]

def ret_423(sr, body=""):
    enc = body.encode()
    sr('423 Locked', [('content-type', 'text/plain')])
    return [enc]

def ret_429(sr, body=""):
    enc = body.encode()
    sr('429 Too Many Requests', [('content-type', 'text/plain')])
    return [enc]

def ret_500(sr, body=""):
    enc = body.encode()
    sr('500 Internal Server Error', [('content-type', 'text/plain')])
    return [enc]

def application(environ, start_response):
    # initialize some variables
    user = environ.get('REMOTE_USER', "")
    query = parse_qs(environ['QUERY_STRING'])
    query = {k: v[0] for k, v in query.items()}
    ip = environ['REMOTE_ADDR']

    # now check our variables
    accepted_keys = ['sseupdate', 'log', 'fulllog', 'section']
    querychecked = any([x in query for x in accepted_keys]) and 'room' in query
    room = query.get("room", "")
    
    # check if room exists
    if not os.path.exists(private + "rooms/" + room + ".db"):
        return ret_404(start_response, "Room does not exist")
    room_db = private + "rooms/" + room + ".db"
    
    # if user is not owner of room, return 403
    owners = getowners(room_db, room) + [x for x in getsections(room) if getsections(room)[x] == "0"]
    if user not in owners:
        return 
    
    # this section handles enabling any student to join a room
    if querychecked and 'log' in query:
        room = query.get("room", "")
        # req.content_type = "application/json"
        # req.send_http_header()
        # req.write(dumps(getdblog(room)[-50:]))
        # return apache.OK
        return ret_json(start_response, dumps(getdblog(room)[-50:]))
    elif querychecked and 'fulllog' in query:
        room = query.get("room", "")
        # req.content_type = "application/json"
        # req.send_http_header()
        # req.write(dumps(getdblog(room)))
        # return apache.OK
        return ret_json(start_response, dumps(getdblog(room)))
    elif querychecked and 'section' in query:
        room = query.get("room", "")
        data = query.get("data", "")
        if data == "":
            # this is a request to get the section data
            # req.write(dumps({"status": "success", "data": sectiondata(room_db, room, "", "get")}))
            return ret_json(start_response, dumps({"status": "success", "data": sectiondata(room_db, room, "", "get")}))
        else:
            # this is a request to set the section data
            try:
                ret = sectiondata(room_db, room, data, "set")
                if ret:
                    return ret_json(start_response, dumps({"status": "success"}))
                else:
                    return ret_json(start_response, dumps({"status": "error"}))
            except:
                return ret_json(start_response, dumps({"status": "fatalerror"}))
    elif querychecked and 'sseupdate' in query:
        return sseupdate(environ, start_response)
    # invalid request
    else:
        return ret_400(start_response, "Invalid request")

def sseupdate(environ, start_response):
    class EventHandler(pyinotify.ProcessEvent):
        def __init__(self, roomname):
            self.roomname = roomname
        def process_IN_MODIFY(self, event):
            data = dumps(getdblog(self.roomname))
            yield ("data: %s\n\r" % data).encode()

    query = parse_qs(environ['QUERY_STRING'])
    query = {k: v[0] for k, v in query.items()}
    room = query.get("room", "")
    
    start_response('200 OK', [
        ('Content-Type', 'text/event-stream;charset=utf-8'),
        ('Cache-Control', 'no-cache;public'),
    ])
    yield b"\n\r"
    
    global wm
    wm = pyinotify.WatchManager()
    notifier = pyinotify.Notifier(wm, EventHandler(room), timeout=30*1000)
    wdd = wm.add_watch(private + 'rooms/' + room + '.db', pyinotify.IN_MODIFY, rec=True)
    # start pyinotify
    while True:
        notifier.process_events()
        while notifier.check_events():
            # above line returns after 30 seconds or if queue is updated
            notifier.read_events()
            notifier.process_events()
        try:
            yield ("data: %s\n\r" % dumps(getdblog(room)[-50:])).encode()
        except:
            wm.close()
            try:
                sys.exit(0)
            except:
                os._exit(0)

MIDDLEWARES = [ ]
app = reduce(lambda h, m: m(h), MIDDLEWARES, application)