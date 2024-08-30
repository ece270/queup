import os
import sys
import sqlite3
from time import time
import redis

# implements a rate limiter class using the token bucket algo 

# takes the username, checks if they have an entry in ratelimit.db, and 
# if so, checks if they have made more than 3 requests in the last second. 
# if so, return false. otherwise, return true and update the database.

class RateLimiter:
    def __init__(self, dbpath, environ):
        self.dbpath = dbpath
        self.environ = environ
    def __enter__(self):
        environ = self.environ
        private = environ['DOCUMENT_ROOT'] + environ['CONTEXT_PREFIX'].replace('~', '') + '/private/queup/'
        try:
            self.conn = redis.Redis(unix_socket_path=open(private + 'redis_socket').read().strip())
        except:
            raise Exception("Database connection failed.  Contact course staff **immediately**.")
        # increment for user with expiration of 1 second
        self.conn.incr('rl:' + environ['REMOTE_USER'])
        self.conn.expire('rl:' + environ['REMOTE_USER'], 1)
        return self
    def __exit__(self, type, value, traceback):
        self.conn.close()
    def should_limit(self, username):
        if int(self.conn.get('rl:' + username).decode('utf8')) > 3:
            return True
        return False