#! /usr/bin/env python3

import os
import json
import re
import sys
import sqlite3
import shutil
import pyinotify

from time import time, sleep
from functools import reduce
from urllib.parse import parse_qs

# predefined here so handler will set their values
room_db = ""

# path to private directory for logs and db files
private = ""

# execute python script with shared global variables
def doexec(path):
    exec(compile(open(path).read(), path, "exec"), globals())

class DBConnection:
    def __init__(self, room_db):
        self.conn = sqlite3.connect(room_db)
        self.cur = self.conn.cursor()
    def __enter__(self):
        return [self.conn, self.cur]
    def __exit__(self, type, value, traceback):
        self.conn.commit()
        self.conn.close()

# MUST be in sync with client side!
ROOM_RGX = r'^[A-Z0-9]{5}$'
QUEUE_RGX = r'^[a-zA-Z0-9\_]{3,15}$'
USER_RGX = r'^[a-z0-9]{2,8}$'
WAITDATA_RGX = r'^[a-zA-Z0-9 \,\_\'\(\)]{1,50}$'
SUBTITLE_RGX = r'^[a-zA-Z0-9 \,\_\'\(\)\-]{1,130}$'
# UP: MUST be in sync with client side!

def createroom(room, user):
    if not re.match(ROOM_RGX, room):
        raise Exception("createroom: Room format incorrect: " + room)
    if "room"+room in getrooms():
        raise Exception("createroom: Room already exists. It may be in use.")
    with DBConnection(room_db) as [conn, cur]:
        cur.execute("CREATE TABLE room{0} (owners TEXT, subtitle TEXT, locked INTEGER, cooldown INTEGER)".format(room))
    # add current user as an owner
    ownroom(room, user)
    # create default_queue
    createqueue("default_queue", room)
    # lock room by default
    # lockroom(room)

def getroomsubtitle(room):
    if not os.path.exists(room_db):
        raise Exception("getroomsubtitle: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("getroomsubtitle: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        # get the subtitle
        subtitle = list(cur.execute("SELECT subtitle FROM room{0}".format(room)))
        if len(subtitle) == 0:
            return ""
        subtitle = subtitle[0]
        return subtitle[0]

def setroomsubtitle(room, subtitle):
    if not os.path.exists(room_db):
        raise Exception("setroomsubtitle: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("setroomsubtitle: Room format incorrect: " + room)
    if subtitle != '' and not re.match(SUBTITLE_RGX, subtitle):
        raise Exception("setroomsubtitle: Bad subtitle: " + subtitle)
    with DBConnection(room_db) as [conn, cur]:
        # set the subtitle
        cur.execute("UPDATE room{0} SET subtitle = (?)".format(room), (subtitle,))

def lockroom(room):
    if not os.path.exists(room_db):
        raise Exception("lockroom: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("lockroom: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        # set the locked value to 1
        cur.execute("UPDATE room{0} SET locked = 1".format(room))

def unlockroom(room):
    if not os.path.exists(room_db):
        raise Exception("unlockroom: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("unlockroom: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        # set the locked value to 0
        cur.execute("UPDATE room{0} SET locked = 0".format(room))

def isroomlocked(room):
    if not os.path.exists(room_db):
        raise Exception("isroomlocked: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("isroomlocked: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        # get the locked value
        locked = list(cur.execute("SELECT locked FROM room{0}".format(room)))
        if len(locked) == 0:
            return False
        locked = locked[0]
        return locked[0] == 1

def ownroom(room, newusers):
    if not os.path.exists(room_db):
        raise Exception("ownroom: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("ownroom: Room format incorrect: " + room)
    # nothing to do if no new users
    if newusers == "":
        return
    if not all([re.match(USER_RGX, x) for x in newusers.split(",")]):
        raise Exception("ownroom: Bad usernames: " + newusers)
    with DBConnection(room_db) as [conn, cur]:
        # get old users first
        oldusers = getowners(room)
        # remove any repeated users
        allusers = list(set(oldusers + newusers.split(",")))
        if len(oldusers) == 0:
            cur.execute("INSERT INTO room{0} (owners) VALUES (?)".format(room), (",".join(allusers),))
        else:
            # set owners value to str of allusers
            cur.execute("UPDATE room{0} SET owners = (?)".format(room), (",".join(allusers),))
            
def delownroom(room, delusers):
    if not os.path.exists(room_db):
        raise Exception("delownroom: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("delownroom: Room format incorrect: " + room)
    # nothing to do if no new users
    if delusers == "":
        return
    if not all([re.match(USER_RGX, x) for x in delusers.split(",")]):
        raise Exception("delownroom: Bad usernames: " + delusers)
    with DBConnection(room_db) as [conn, cur]:
        # get old users first
        oldusers = getowners(room)
        # remove users that are in delusers
        allusers = [x for x in oldusers if str(x) not in delusers.split(",")]
        if len(allusers) == 0:
            # cur.execute("INSERT INTO room{0} (owners) VALUES (?)".format(room), (",".join(allusers),))
            raise Exception("The room cannot have no owners!")
        else:
            # set owners value to str of allusers
            cur.execute("UPDATE room{0} SET owners = (?)".format(room), (",".join(allusers),))

def getowners(room):
    if not os.path.exists(room_db):
        return []
    if not re.match(ROOM_RGX, room):
        raise Exception("getowners: Room format incorrect: " + room)
    sectiondata = getsections(room)
    # if any users have "0" as their section, then they are owners
    owners = [x for x in sectiondata if sectiondata[x] == "0"]
    with DBConnection(room_db) as [conn, cur]:
        allusers = list(cur.execute("SELECT owners FROM room{0}".format(room)))
        if len(allusers) == 0:
            return []
        allusers = allusers[0]
        allusers = allusers[0].split(",")
        allusers = list(set(allusers + owners))
        return allusers

def deleteroom(room):
    if not os.path.exists(room_db):
        raise Exception("deleteroom: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("deleteroom: Room format incorrect: " + room)
    # find queues associated with room
    queues = getqueues(room)
    # delete all queues associated with room
    for queue in queues:
        deletequeue(queue, room)
    # delete the room from the db (IMPORTANT as it triggers sseupdate to close client-side)
    with DBConnection(room_db) as [conn, cur]:
        cur.execute("DROP TABLE room{0}".format(room))
    # delete sections if they exist
    if os.path.exists(private + "sections/" + room + ".json"):
        os.remove(private + "sections/" + room + ".json")
    # finally, delete the room database file
    os.remove(room_db)

def createqueue(queue, room):
    if not os.path.exists(room_db):
        raise Exception("createqueue: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    with DBConnection(room_db) as [conn, cur]:
        if "room" + room not in [x[0] for x in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            raise Exception("The room {0} did not exist.".format(room))
        if not re.match(QUEUE_RGX, queue):
            raise Exception("createqueue: Bad queue name: " + queue)
        # ensure queue table does not exist already
        # makes sure that anyone on there is no longer there
        if "room" + room + "_queue" + queue in [x[0] for x in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            deletequeue(queue, room)
        # create the queue table
        cur.execute("CREATE TABLE room{0}_queue{1} (username TEXT KEY, time REAL, data TEXT, marked INTEGER)".format(room, queue))
        return True

def renamequeue(oldqueue, newqueue, room):
    if not os.path.exists(room_db):
        raise Exception("renamequeue: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    with DBConnection(room_db) as [conn, cur]:
        # ensure queue table exists
        if "room" + room + "_queue" + oldqueue not in [x[0] for x in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            raise Exception("renamequeue: Queue {0} did not exist.".format(oldqueue))
        if not re.match(ROOM_RGX, room):
            raise Exception("renamequeue: Room format incorrect: " + room)
        if not re.match(QUEUE_RGX, newqueue):
            raise Exception("renamequeue: Bad queue name: " + newqueue)
        # create the queue table
        cur.execute("ALTER TABLE room{0}_queue{1} RENAME TO room{0}_queue{2}".format(room, oldqueue, newqueue))
        return True

def deletequeue(queue, room):
    if not os.path.exists(room_db):
        raise Exception("deletequeue: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("deletequeue: Room format incorrect: " + room)
    elif not re.match(QUEUE_RGX, queue):
        raise Exception("deletequeue: Bad queue name: " + queue)
    with DBConnection(room_db) as [conn, cur]:
        # delete the queue table if it exists
        if "room" + room + "_queue" + queue in [x[0] for x in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            cur.execute("DROP TABLE room{0}_queue{1}".format(room, queue))

def setcooldown(cooldown, room):
    if not os.path.exists(room_db):
        raise Exception("setcooldown: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("setcooldown: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        # set the cooldown value
        cur.execute("UPDATE room{0} SET cooldown = ?".format(room), (str(cooldown),))
    
def getcooldown(room):
    if not os.path.exists(room_db):
        raise Exception("getcooldown: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if not re.match(ROOM_RGX, room):
        raise Exception("getcooldown: Room format incorrect: " + room)
    with DBConnection(room_db) as [conn, cur]:
        # get the cooldown value
        cooldown = list(cur.execute("SELECT cooldown FROM room{0}".format(room)))
        if len(cooldown) == 0:
            return 0
        if cooldown[0][0] == None:
            setcooldown(0, room)
            cooldown = 0
        else:
            cooldown = int(cooldown[0][0])
        return cooldown

def addquser(user, waitdata, queue, room):
    if not os.path.exists(room_db):
        raise Exception("addquser: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if queue == "":
        raise Exception("addquser: No queue provided")
    elif room == "":
        raise Exception("addquser: No room provided")
    elif not re.match(ROOM_RGX, room):
        raise Exception("addquser: Room format incorrect: " + room)
    elif not re.match(QUEUE_RGX, queue):
        raise Exception("addquser: Bad queue name: " + queue)
    elif not re.match(USER_RGX, user):
        raise Exception("addquser: Bad username: " + user)
    elif waitdata != '' and not re.match(WAITDATA_RGX, waitdata):
        raise Exception("addquser: Bad waitdata: " + waitdata)
    with DBConnection(room_db) as [conn, cur]:
        cur.execute("INSERT INTO room{0}_queue{1} (username, time, data, marked) VALUES (?, ?, ?, ?)".format(room, queue), (user, time(), waitdata, '0'))

def delquser(user, queue, room):
    if not os.path.exists(room_db):
        raise Exception("delquser: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if queue == "":
        raise Exception("delquser: No queue provided")
    elif room == "":
        raise Exception("delquser: No room provided")
    elif not re.match(ROOM_RGX, room):
        raise Exception("delquser: Room format incorrect: " + room)
    elif not re.match(QUEUE_RGX, queue):
        raise Exception("delquser: Bad queue name: " + queue)
    elif not re.match(USER_RGX, user):
        raise Exception("delquser: Bad username: " + user)
    with DBConnection(room_db) as [conn, cur]:
        cur.execute("DELETE FROM room{0}_queue{1} WHERE username == ?".format(room, queue), (user,))

def getrooms():
    if not os.path.exists(room_db):
        return []
    with DBConnection(room_db) as [conn, cur]:
        # get all rooms, then get all room data
        with conn:
            roomnames = [str(row[0]) for row in cur.execute('SELECT name FROM sqlite_master') if row[0].startswith("room") and "queue" not in row[0]]
        return roomnames

def getqueues(room):
    if not os.path.exists(room_db):
        raise Exception("getqueues: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    with DBConnection(room_db) as [conn, cur]:
        if room == "":
            return [row[0] for row in cur.execute("SELECT name FROM sqlite_master") if re.match(r'room[A-Z0-9]{5}_queue.*', row[0])]
        else:
            # get all queues in room
            return [str(row[0].replace("room{0}_queue".format(room), "")) for row in cur.execute("SELECT name FROM sqlite_master") if row[0].startswith("room{0}_queue".format(room))]

def getlastadd(room, username):
    if not os.path.exists(private + "room.log"):
        return 0    # no one could have added themselves to this queue at UNIX epoch!
    with open(private + "room.log", "r") as f:
        data = [x.split(",") for x in f.read().split("\n") if room in x and username in x and "uadd" in x]
    if len(data) == 0:
        return 0    # no one could have added themselves to this queue at UNIX epoch!
    return float(data[-1][0])   # but we can find out when they did it last

def getusers(queue, room):
    if not os.path.exists(room_db):
        raise Exception("getusers: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    with DBConnection(room_db) as [conn, cur]:
        # we don't need to check if room == "" because getqueues does that for us
        if queue == "":
            queues = sorted(getqueues(room))
            all_users = {}
            for _q in queues:
                if room == "":
                    r = _q.split("_")[0].replace("room", "")
                else:
                    r = room
                q = _q
                if r not in all_users:
                    all_users[r] = {}
                arr = sorted([row for row in cur.execute("SELECT username, time, data, marked FROM room{0}_queue{1}".format(r, q))])
                # add section for each student from private + "sections/" + room + ".json"
                if os.path.exists(private + "sections/" + r + ".json"):
                    with open(private + "sections/" + r + ".json", "r") as f:
                        sections = json.loads(f.read())
                else:
                    sections = {}
                for row in arr:
                    # sections is {username: section}
                    if row[0] in sections:
                        idx = arr.index(row)
                        row = list(row)
                        row.append(sections[row[0]])
                        arr[idx] = tuple(row)
                    else:
                        arr[arr.index(row)] = row + ("",)
                all_users[r][q] = arr
            return all_users
        else:
            # get all users in queue
            return sorted([row for row in cur.execute("SELECT username, time, data, marked FROM room{0}_queue{1}".format(room, queue))])

def getsections(room):
    if not os.path.exists(private + "sections/" + room + ".json"):
        return {}
    with open(private + "sections/" + room + ".json", "r") as f:
        sections = json.loads(f.read())
    return sections

def getsectionforuser(user, room):
    if not os.path.exists(private + "sections/" + room + ".json"):
        return ""
    sections = getsections(room)
    if user in sections:
        return sections[user]
    else:
        return ""

def togglemark(user, queue, room):
    if not os.path.exists(room_db):
        raise Exception("togglemark: " + room_db.split("/")[-1].replace(".db", "") + " does not exist.")
    if queue == "":
        raise Exception("togglemark: No queue provided")
    elif room == "":
        raise Exception("togglemark: No room provided")
    elif not re.match(ROOM_RGX, room):
        raise Exception("togglemark: Room format incorrect: " + room)
    elif not re.match(QUEUE_RGX, queue):
        raise Exception("togglemark: Bad queue name: " + queue)
    elif not re.match(USER_RGX, user):
        raise Exception("togglemark: Bad username: " + user)
    with DBConnection(room_db) as [conn, cur]:
        # get the marked value
        marked = list(cur.execute("SELECT marked FROM room{0}_queue{1} WHERE username == ?".format(room, queue), (user,)))
        # if marked is empty, then user is not in queue
        if len(marked) == 0:
            raise Exception("togglemark: User {0} not in queue {1} in room {2}".format(user, queue, room))
        marked = marked[0]
        # toggle the marked value
        cur.execute("UPDATE room{0}_queue{1} SET marked = ? WHERE username == ?".format(room, queue), (1 - int(marked[0]), user))
        return True

def getroompermanency(room):
    if not os.path.exists(private + "nodel_rooms"):
        return False
    with open(private + "nodel_rooms", "r") as f:
        return room in f.read().split("\n")

def acquireLock(path):
    t = 0
    while t < 5 and os.path.exists(path + ".lck"):
        sleep(1)
        t += 1
    if t == 5:
        raise Exception("lockdir " + path + ".lck" + " not removed.")
    try:
        os.mkdir(path + ".lck")
    except:
        raise Exception("Unable to create lockdir")
    return path + ".lck"

def releaseLock(lock):
    if os.path.exists(lock):
        try:
            shutil.rmtree(lock)
        except:
            raise Exception("Unable to remove lockdir")

def lockAndWriteLog(data):
    global private
    lock = acquireLock(private + "room.log")
    with open(private + "room.log", "a+") as f:
        f.write(data + "\n")
    releaseLock(lock)

class Lock:
    def __init__(self, lockdir):
        self.lockdir = lockdir
        self.lock = None
    def __enter__(self):
        self.lock = acquireLock(self.lockdir)
        return self.lock
    def __exit__(self, type, value, traceback):
        releaseLock(self.lock)

# implement a rate limiter class using the token bucket algo 
# that takes the username, checks if they have an entry in 
# ratelimit.db, and if so, checks if they have made more than 
# 3 requests in the last second. if so, return false. otherwise, 
# return true and update the database.

class RateLimiter:
    def __init__(self, dbpath):
        self.dbpath = dbpath
    def __enter__(self):
        create = not os.path.exists(self.dbpath)
        self.conn = sqlite3.connect(self.dbpath)
        self.cur = self.conn.cursor()
        if create:
            with self.conn:
                self.cur.execute("CREATE TABLE ratelimit (username TEXT KEY, time REAL)")
        return [self, self.conn, self.cur]
    def __exit__(self, type, value, traceback):
        self.conn.commit()
        self.conn.close()
    def should_limit(self, username):
        # get the last 5 requests
        last5 = [x[0] for x in self.cur.execute("SELECT time FROM ratelimit WHERE username == (?) ORDER BY time DESC LIMIT 5", (username,))]
        # if there are less than 5 requests, then we're good
        if len(last5) < 5:
            self.cur.execute("INSERT INTO ratelimit (username, time) VALUES (?, ?)", (username, time()))
            return False
        # if the last request was more than a second ago, we're good
        if time() - last5[-1] > 1:
            self.cur.execute("INSERT INTO ratelimit (username, time) VALUES (?, ?)", (username, time()))
            return False
        # otherwise, we're not good
        return True

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
    global ip, room_db, private
    
    # grab config based on IP and init all variables
    private = environ['DOCUMENT_ROOT'] + environ['CONTEXT_PREFIX'] + '/private/queup/'
    
    # initialize some variables from wsgi environment
    user = environ.get('REMOTE_USER', "")
    if user == "":
        return ret_401(start_response, "No user provided.")
    
    # check rate limit for this user
    with RateLimiter(private + "ratelimit.db") as [rl, conn, cur]:
        if rl.should_limit(user):
            return ret_429(start_response, "Rate limit exceeded.")

    query = parse_qs(environ['QUERY_STRING'])
    # change values to strings
    query = {k: v[0] for k, v in query.items()}
    ip = environ['REMOTE_ADDR']

    room = query.get('room', '')
    if len(room) != 5 or not re.search(r"[A-Z0-9]{5}", room):
        # req.log_error("Invalid room name: " + room + "\n")
        return ret_400(start_response, "Invalid room name " + room)
    action = query.get('action', '')
    actions = ['add', 'del', 'chk', 'ren', 'own', 'delown', 'setcool', 'setsub', 'lock', 'unlock', 'clear', 'mark']
    if 'sseupdate' not in query and not (action in actions):
        # req.log_error("Invalid action: " + action + "\n")
        return ret_400(start_response, "Invalid action " + action)
    setup = query.get('setup', '')
    roomsetup = (setup != '') and (action != '') and (room != '') and 'queue' not in query
    queuesetup = (setup != '') and (action != '') and (room != '') and 'queue' in query
    querychecked = setup == '' and (action != '') and (room != '') and 'queue' in query

    # do we have a room to access? then we must be either its owner or we must 
    # be chk, sseupdate, or adding/deleting ourselves from a queue (no setup)
    room_db = private + "rooms/" + room + ".db"
    
    # is user owner? set to true if room doesn't exist, must be owner to create room
    if os.path.exists(room_db):
        try:
            is_owner = user in getowners(room)
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                # file exists but table does not, seems like a mistake.
                # remove it and recreate.
                os.remove(room_db)
        conditions_for_access_nodb = [
            action in ['chk'],
            'sseupdate' in query,
            (action in ['add', 'del'] and querychecked)
        ]
        # if db exists, but we're not add/del to a queue, and we're not owner,
        # then bad request.
        if not any(conditions_for_access_nodb) and not is_owner:
            # req.log_error("FailedReqCheck: user not in getowners(room) and roomsetup. getowners: " + str(getowners(room)))
            return ret_400(start_response, "Illegal action for non-owner.")
    elif roomsetup and action == 'add':
        # db does not exist and roomsetup+add means we are creating a room
        is_owner = True
    else:   # so no db exists, and we're not creating one. what's the point?
        return ret_400(start_response, "Malformed request.")
    
    newusers = query.get('newusers', '')
    subtitle = query.get('subtitle', '')

    # now check our variables
    rooms = getrooms()

    # set section
    section = getsectionforuser(user, room)

    # this section handles adding and removing in a room
    if roomsetup:
        # check actions based on whether adding/deleting
        will_add     = action == 'add'  # room should not be in the database already
        will_del     = action == 'del' and "room"+room in rooms # room is in the database
        will_chk     = action == 'chk' and "room"+room in rooms # room is in the database
        will_own     = action == 'own' and "room"+room in rooms # room is in the database
        will_own     = will_own and (newusers == "" or all([re.match(USER_RGX, x) for x in newusers.split(",")]))
        will_delown  = action == 'delown' and "room"+room in rooms # room is in the database
        will_delown  = will_delown and (newusers == "" or all([re.match(USER_RGX, x) for x in newusers.split(",")]))
        will_setsub  = action == 'setsub' and "room"+room in rooms # room is in the database
        will_setsub  = will_setsub and (subtitle == "" or re.match(SUBTITLE_RGX, subtitle))
        will_tgllock = action in ['lock', 'unlock'] and "room"+room in rooms # room is in the database
        will_setcool = action == 'setcool' and "room"+room in rooms # room is in the database
        # perform the action
        if will_add:
            try:
                createroom(room, user)
            except Exception as e:
                return ret_400(start_response, str(e))
            rooms = getrooms()
            userdata = getusers("", room)
            userdata["is-owner"] = is_owner
            userdata["section"] = section
            userdata["cooldown"] = getcooldown(room)
            if is_owner:
                userdata["owners"] = getowners(room)
            userdata["subtitle"] = ""
            userdata["is-locked"] = False
            # it is possible to define a room first before creating it, so check permanency anyway
            userdata["is-permanent"] = getroompermanency(room)
            lockAndWriteLog(",".join([str(time()), user, "rcreate", room]))
            return ret_json(start_response, json.dumps(userdata))
        elif will_chk:
            if "room"+room not in rooms:
                return ret_400(start_response, "Room not found in database. May be misconfigured." % room)
            userdata = getusers("", room)
            userdata["is-owner"] = is_owner
            userdata["section"] = section
            userdata["cooldown"] = getcooldown(room)
            if is_owner:
                userdata["owners"] = getowners(room)
            userdata["subtitle"] = getroomsubtitle(room)
            userdata["is-locked"] = isroomlocked(room)
            userdata["is-permanent"] = getroompermanency(room)
            if "admin" not in query or not is_owner:
                lockAndWriteLog(",".join([str(time()), user, "rchk", room]))
            return ret_json(start_response, json.dumps(userdata))
        else:
            if not is_owner:
                return ret_401(start_response, "User is not an owner of room.")
            try:
                if will_del:
                    if room in open(private + "nodel_rooms").read():
                        return ret_400(start_response, "Room is permanent.")
                    deleteroom(room)
                    lockAndWriteLog(",".join([str(time()), user, "rdel", room]))
                    return ret_json(start_response, json.dumps({"status": "success"}))
                elif will_own:
                    ownroom(room, newusers)
                    lockAndWriteLog(",".join([str(time()), user, "rown", room, newusers]))
                    return ret_json(start_response, json.dumps(getowners(room)))
                elif will_delown:
                    delownroom(room, newusers)
                    lockAndWriteLog(",".join([str(time()), user, "rdelown", room, newusers]))
                    return ret_json(start_response, json.dumps(getowners(room)))
                elif will_setsub:
                    setroomsubtitle(room, subtitle)
                    lockAndWriteLog(",".join([str(time()), user, "rsub", room, subtitle]))
                    return ret_json(start_response, json.dumps({"status": "success"}))
                elif will_tgllock:
                    if action == 'unlock':
                        unlockroom(room)
                        lockAndWriteLog(",".join([str(time()), user, "runlock", room]))
                    else:
                        lockroom(room)
                        lockAndWriteLog(",".join([str(time()), user, "rlock", room]))
                    return ret_json(start_response, json.dumps({"status": "success"}))
                elif will_setcool:
                    cooldown = int(query.get('cooldown', ''))
                    setcooldown(cooldown, room)
                    lockAndWriteLog(",".join([str(time()), user, "rcool", room, str(cooldown)]))
                    return ret_json(start_response, json.dumps({"status": "success"}))
                else:
                    return ret_400(start_response, "No valid query.")
            except sqlite3.IntegrityError:  # our fault
                return ret_500(start_response, "IntegrityError running action.")
            except: # their fault
                return ret_400(start_response, "Unrecognized error running action.")
    elif queuesetup:
        if not is_owner:
            return ret_401(start_response, "User is not an owner of room.")
        room = query.get('room', '')
        queue = query.get('queue', '')
        if len(room) != 5 or not re.search(ROOM_RGX, room):
            return ret_400(start_response, "Invalid room name.")
        if not re.search(QUEUE_RGX, queue):
            return ret_400(start_response, "Invalid room name.")
        queue = query.get('queue', '')
        newqueue = query.get('newqueue', '')
        username = query.get('username', '')
        # check actions based on whether adding/deleting/checking/renaming
        will_add = query.get('action', '') == 'add'
        will_del = query.get('action', '') == 'del' and "room"+room in rooms # room is in the database
        will_del = will_del and queue in getqueues(room) # queue was in the database
        will_chk = query.get('action', '') == 'chk' and "room"+room in rooms # room is in the database
        will_chk = will_chk and queue in getqueues(room) # queue was in the database
        will_ren = query.get('action', '') == 'ren' and "room"+room in rooms # room is in the database
        will_ren = will_ren and queue in getqueues(room) # queue was in the database
        will_ren = will_ren and re.match(QUEUE_RGX, newqueue) and newqueue not in getqueues(room) # new queue must not already exist and newqueue != ''
        will_clear = query.get('action', '') == 'clear' and "room"+room in rooms # room is in the database
        will_clear = will_clear and queue in getqueues(room) # queue was in the database
        will_mark = query.get('action', '') == 'mark' and "room"+room in rooms # room is in the database
        will_mark = will_mark and queue in getqueues(room) and any([username == x[0] for x in getusers(queue, room)])   # queue was in the database and user is in the queue
        # perform the action
        if will_add or will_del or will_ren or will_clear or will_mark:
            try:
                if will_add:
                    try:
                        createqueue(queue, room)
                    except sqlite3.OperationalError as e:
                        if "already exists" in str(e):
                            pass
                    lockAndWriteLog(",".join([str(time()), user, "qadd", room, queue]))
                    return ret_ok(start_response, json.dumps(getusers("", room)))
                elif will_del:
                    # queue cannot be the only queue in the room!
                    if len(getqueues(room)) == 1:
                        return ret_400(start_response, "Cannot delete the only queue in a room.")
                    deletequeue(queue, room)
                    lockAndWriteLog(",".join([str(time()), user, "qdel", room, queue]))
                    return ret_ok(start_response, json.dumps(getusers("", room)))
                elif will_ren:
                    renamequeue(queue, newqueue, room)
                    lockAndWriteLog(",".join([str(time()), user, "qren", room, queue, newqueue]))
                    return ret_ok(start_response, json.dumps(getusers("", room)))
                elif will_clear:
                    # get all users and remove them from the queue
                    for u in getusers(queue, room):
                        delquser(u[0], queue, room)
                    lockAndWriteLog(",".join([str(time()), user, "qclr", room, queue]))
                    return ret_ok(start_response, json.dumps(getusers("", room)))
                elif will_mark:
                    # toggle mark on user
                    togglemark(username, queue, room)
                    lockAndWriteLog(",".join([str(time()), user, "qmrk", room, queue, username]))
                    return ret_ok(start_response, json.dumps(getusers("", room)))
                else:
                    return ret_400(start_response, "No valid query.")
            except sqlite3.IntegrityError: 
                return ret_500(start_response, "IntegrityError.")
            except Exception as e:
                return ret_ok(start_response, str(e))
        elif will_chk:
            return ret_ok(start_response, json.dumps(getusers("", room)))
        else:
            return ret_400(start_response, "Invalid action.")
    elif querychecked:
        room = query.get('room', '')
        queue = query.get('queue', '')
        username = query.get('username', '')
        if room == '' or "room"+room not in rooms or queue == '' or queue not in getqueues(room):
            return ret_400(start_response, "Invalid room/queue name.")
        # room name should already be in database
        db_queue = getusers(queue, room)
        # check if room is locked before adding anyone unless we are owner
        # perform actions based on whether adding/deleting (will_del does not include owner deleting users)
        will_add = action == 'add' and not any([user == x[0] for x in db_queue]) # username should not be in the room already
        will_del = action == 'del' and any([user == x[0] for x in db_queue]) and (username == '') # username was in the room and is not someone else or empty
        staff_del = is_owner and action == 'del' and username is not None and any([username == x[0] for x in db_queue]) # username was in the room
        if isroomlocked(room) and not is_owner and will_add:
            return ret_423(start_response, "Room is locked.")
        # only make changes to database if changes are to be made
        try:
            if will_add:
                # check if there is a cooldown period, and that user is not adding themselves more than
                # COOLDOWN minutes since their last add
                cooldown = getcooldown(room)
                if cooldown > 0:
                    lastadd = getlastadd(room, user)
                    if (time() - lastadd) < (cooldown * 60):
                        rem_min = int(cooldown - (time() - lastadd) / 60)
                        rem_sec = int((cooldown - (time() - lastadd) / 60) % 1 * 60)
                        return ret_ok(start_response, "[cooldown] This room only permits you to add yourself to any queue every %d minutes. Please wait %d minutes and %s seconds before adding yourself again." % (cooldown, rem_min, rem_sec))
                waitdata = query.get('waitdata', '')
                if waitdata != '' and not re.match(WAITDATA_RGX, waitdata):
                    return ret_400(start_response, "Invalid waitdata.")
                addquser(user, waitdata, queue, room)
                lockAndWriteLog(",".join([str(time()), user, "uadd", room, queue, waitdata]))
                ret_ok(start_response, "success")
            elif will_del:
                delquser(user, queue, room)
                lockAndWriteLog(",".join([str(time()), user, "udel", room, queue]))
                ret_ok(start_response, "success")
            elif staff_del:
                # owner is removing someone from the queue
                delquser(username, queue, room)
                lockAndWriteLog(",".join([str(time()), user, "usdel", room, queue, username]))
                ret_ok(start_response, "success")
            else:
                return ret_400(start_response, "Invalid action.")
        except sqlite3.IntegrityError: 
            return ret_500(start_response, "IntegrityError.")
        except Exception as e:
            return ret_400(start_response, str(e))
        return ret_ok(start_response, "success")
    #
    # Otherwise it is waiting for updates
    #
    elif 'sseupdate' in query:
        return sseupdate(environ, start_response)
    else:
        return ret_400(start_response, "Invalid request.")

def sseupdate(environ, start_response):
    class EventHandler(pyinotify.ProcessEvent):
            def __init__(self, roomname):
                self.roomname = roomname
            def process_IN_MODIFY(self, event):
                yield ("data: %s\n\r" % json.dumps(getusers("", self.roomname))).encode()
    
    query = parse_qs(environ['QUERY_STRING'])
    query = {k: v[0] for k, v in query.items()}
    rooms = getrooms()

    room = query.get('room', '')
    if room == '' or "room"+room not in rooms:
        sys.stderr.write("Room %s not found in database\n" % room)
        return ret_400(start_response, "Room not found in database.")
    
    start_response('200 OK', [
        ('Content-Type', 'text/event-stream;charset=utf-8'),
        ('Cache-Control', 'no-cache;public'),
    ])

    yield ("data: %s\n\n" % json.dumps(getusers("", room))).encode()
    wm = pyinotify.WatchManager()
    notifier = pyinotify.Notifier(wm, EventHandler(room), timeout=120*1000)
    wds = wm.add_watch(room_db, pyinotify.IN_MODIFY, rec=True)
    wd = wds[room_db]
    # start pyinotify
    notifier.process_events()
    while notifier.check_events(timeout=120*1000):
        # above line returns after 30 seconds or if room is updated
        notifier.read_events()
        notifier.process_events()
        try:
            yield ("data: %s\n\n" % json.dumps(getusers("", room))).encode()
        except:
            wm.rm_watch(room_db)
            wm.close()
            try:
                sys.exit(0)
            except:
                os._exit(0)
    # if we reach this point, no events have occurred whatsoever, 
    # so we must exit
    wm.rm_watch(wd)
    wm.close()
    return "data: %s\n\n" % json.dumps(getusers("", room))
    

MIDDLEWARES = [ ]
app = reduce(lambda h, m: m(h), MIDDLEWARES, application)