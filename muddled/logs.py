import SocketServer
import copy
import os
import socket
import struct
import cPickle
import threading
import random
import sys

import logging
import logging.handlers
import logging.config


# Python is unable to manage multiple processes writing to the same file so main threads create a
# socket server that any other muddle running in the same directory connects to.
from muddled.utils import MuddleBug

file_level = 'INFO'

# most test scripts depend on term_level being WARNING
term_level = 'WARNING'

base_dict = {
    'version': 1,
    'disable_existing_loggers': False,
    # doesn't disable all loggers created before this is executed, shouldn't be necessary
    # but it is possible something will use muddle as a library rather than an executable.

    'formatters': {
        'standard': {
            'format': '%(asctime)-15s [%(levelname)-8s] %(process)-5s %(name)-20s: %(message)s'
        },
        'simple': {
            'format': '%(message)s'
        },
    },
    'filters': {
        'local_filter': {
            (): 'LocalFilter'
        }
    },
    'handlers': {
        'console': {
            'level': term_level,
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'filters': ['local_filter'],
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        # assumes that the file_level will log more than or equal to term_level
        'level': file_level,
        'propagate': True
    }
}
server_dict = copy.deepcopy(base_dict)
server_dict['handlers']['file'] = {
    'level': file_level,
    'class': 'logging.handlers.RotatingFileHandler',
    'formatter': 'standard',
    'filename': '.muddle.log',
    'delay': True,
    'mode': 'a',
    'backupCount': 50,
    # keeps logs for the last 50 non-internal commands
}
server_dict['root']['handlers'].append('file')
client_dict = copy.deepcopy(base_dict)
client_dict['handlers']['socket'] = {
    'level': file_level,
    'class': 'logging.handlers.SocketHandler',
    'formatter': 'standard',
    'host': 'localhost',
    'port': logging.handlers.DEFAULT_TCP_LOGGING_PORT,
}
client_dict['root']['handlers'].append('socket')


class LocalFilter(logging.Filter):
    def __init__(self):
        self.pid = os.getpid()
        super(LocalFilter, self).__init__()


    def filter(self, record):
        if record.level >= logging.WARNING:
            return True
        # if record.process != self.pid:
        # print record.__dict__
        #     record.msg += "NOT LOCAL"
        #     record.message += "NOT LOCAL"
        # return True
        return record.process == self.pid


# from https://docs.python.org/2.7/howto/logging-cookbook.html#network-logging
class LogRecordStreamHandler(SocketServer.StreamRequestHandler):
    """Handler for a streaming logging request.

    This basically logging the record using whatever logging policy is
    configured locally.
    """

    def handle(self):
        """
        Handle multiple requests - each expected to be a 4-byte length,
        followed by the LogRecord in pickle format. logging the record
        according to whatever policy is configured locally.
        """
        while True:
            chunk = self.connection.recv(4)
            if len(chunk) < 4:
                break
            slen = struct.unpack('>L', chunk)[0]
            chunk = self.connection.recv(slen)
            while len(chunk) < slen:
                chunk = chunk + self.connection.recv(slen - len(chunk))
            obj = cPickle.loads(chunk)
            record = logging.makeLogRecord(obj)
            self.handle_log_record(record)

    def handle_log_record(self, record):
        # if a name is specified, we use the named logger rather than the one
        # implied by the record.
        if self.server.logname is not None:
            name = self.server.logname
        else:
            name = record.name
        logger = logging.getLogger(name)
        # N.B. EVERY record gets logged. This is because Logger.handle
        # is normally called AFTER logger-level filtering. If you want
        # to do filtering, do it at the client end to save wasting
        # cycles and network bandwidth!
        logger.handle(record)


# from https://docs.python.org/2.7/howto/logging-cookbook.html#network-logging
class LogRecordSocketReceiver(SocketServer.ThreadingTCPServer):
    """
    Simple TCP socket-based logging receiver suitable for testing.
    """

    allow_reuse_address = 1

    def __init__(self, host='localhost',
                 port=logging.handlers.DEFAULT_TCP_LOGGING_PORT,
                 handler=LogRecordStreamHandler):
        SocketServer.ThreadingTCPServer.__init__(self, (host, port), handler)
        self.abort = 0
        self.timeout = 1
        self.logname = None

    def serve_until_stopped(self):
        import select

        abort = 0
        while not abort:
            rd, wr, ex = select.select([self.socket.fileno()], [], [],
                                       self.timeout)
            if rd:
                self.handle_request()
            abort = self.abort


def init(root=None):
    if not root:
        root = os.path.abspath(os.getcwd())
        log_file = os.path.join(root, '.muddle.log')
        # No .muddle directory to nicely contain the log file

        server_dict['handlers']['file']['level'] = term_level
        # so by preference don't litter random directories with .muddle.log files
        # unless there is something at least moderately important to record

    else:
        log_file = os.path.join(root, '.muddle/log')

    random.seed(root)
    # Not necessarily ideal behaviour but it allows multiple muddle builds to run simultaneusly
    port = random.randint(49152, 65535)
    try:
        tcpserver = LogRecordSocketReceiver(port=port)
        thread = threading.Thread(target=tcpserver.serve_until_stopped)
        thread.daemon = True
        thread.start()
        server_dict['handlers']['file']['filename'] = log_file
        # print "logging to %s" % log_file
        logging.config.dictConfig(server_dict)

        rolled = False
        # Increments number on each log file and starts writing on the newly cleared muddle.log
        # If there are already handler.backupCount old logs then the oldest will be deleted
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'doRollover'):
                handler.doRollover()
                rolled=True
        if not rolled:
            raise MuddleBug("logging seems to be missing a rotating file handler on the root logger?")
        if "_sub" in " ".join(sys.argv[1:]):
            raise MuddleBug("running socket server debug for non-internal process")
    except socket.error:
        # assumed to be erroring because the socket is bound by a relevant main muddle process
        client_dict['handlers']['socket']['port'] = port
        logging.config.dictConfig(client_dict)
        if "_sub" not in " ".join(sys.argv[1:]):
            raise MuddleBug("running socket client debug for internal process")
        # logging.getLogger("test").warning("!!!!TEST WARNING in %s for %s" % (os.getcwd(), root))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("muddled").info("Started with 'muddle %s'" % " ".join(sys.argv[1:]))
