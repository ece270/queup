import os
import sys
import sqlite3
from time import time

# implements a rate limiter class using the token bucket algo 

# takes the username, checks if they have an entry in ratelimit.db, and 
# if so, checks if they have made more than 3 requests in the last second. 
# if so, return false. otherwise, return true and update the database.

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