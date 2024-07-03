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
    sr('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(enc)))])
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
