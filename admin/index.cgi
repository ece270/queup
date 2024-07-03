#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os, io, sys, codecs, redis, re

sys.stderr.write("environ: %s\n" % str(os.environ))

sys.path.append(os.environ['CONTEXT_DOCUMENT_ROOT'] + '/queup')
from lib.lock import *
from lib.methods import ROOM_RGX, getowners, getsections, getrooms
from lib.ratelimiter import *
from lib.wsgidefs import *

sys.path.append(os.environ['CONTEXT_DOCUMENT_ROOT'] + '/queup/admin')
from alib.methods import *

username = os.environ['REMOTE_USER']
query = os.environ['QUERY_STRING']

parse_qs = {}
for pair in query.split("&"):
    if pair == "":
        continue
    key, value = pair.split("=")
    parse_qs[key] = value

if "@purdue.edu" in username:
    print("Content-Type: text/plain\r\n")
    print("Please log in with your username, not your email.  You may need to clear site settings and try again.")
    sys.exit(0)

# enables unicode printing
sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

private = os.environ['CONTEXT_DOCUMENT_ROOT'] + "../private/queup/"

try:
    rds = redis.Redis(unix_socket_path=open(private + 'redis_socket').read().strip())
except:
    print("Content-Type: text/plain\r\n")
    print("Database connection failed.  Contact course staff **immediately**.")
    sys.exit(0)

# load the HTML
print ("Content-Type: text/html\r\n")
if "room" not in parse_qs:
    print("<h3>Please specify a room.</h3>")
else:
    room = parse_qs["room"]
    # check if room is real
    if not re.search(ROOM_RGX, room) or not rds.get("room"+room):
        print("<h3>Room does not exist.</h3>")
        sys.exit(0)
    # check if user is in owners list
    room = parse_qs["room"]
    owners = getowners(room)
    sectiondata = getsections(room)
    owners += [x for x in sectiondata if sectiondata[x] == "0"]
    if username not in owners:
        print("<h3>You are not an owner of this room.  Access has been logged.</h3>")
        sys.exit(0)
    with io.open('app.html', 'r', encoding='utf8') as file:
        # fill username
        data = file.read().replace("--username--", username)
        # fill room
        data = data.replace("--room--", parse_qs["room"])
        # send HTML
        print(data)
