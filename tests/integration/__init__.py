# Copyright 2016 DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

try:
    import unittest2 as unittest
except ImportError:
    import unittest  # noqa
from packaging.version import Version
import logging
import os
import socket
import sys
import time
import traceback
import platform
from threading import Event
from subprocess import call
from itertools import groupby

from dse import OperationTimedOut, ReadTimeout, ReadFailure, WriteTimeout, WriteFailure, AlreadyExists,\
    InvalidRequest
from dse.cluster import Cluster
from dse.protocol import ConfigurationException
from dse import ProtocolVersion


try:
    from ccmlib.cluster import Cluster as CCMCluster
    from ccmlib.dse_cluster import DseCluster
    from ccmlib.cluster_factory import ClusterFactory as CCMClusterFactory
    from ccmlib import common
except ImportError as e:
    CCMClusterFactory = None

log = logging.getLogger(__name__)

CLUSTER_NAME = 'test_cluster'
SINGLE_NODE_CLUSTER_NAME = 'single_node'
MULTIDC_CLUSTER_NAME = 'multidc_test_cluster'

CCM_CLUSTER = None

path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'ccm')
if not os.path.exists(path):
    os.mkdir(path)

cass_version = None
cql_version = None


def get_server_versions():
    """
    Probe system.local table to determine Cassandra and CQL version.
    Returns a tuple of (cassandra_version, cql_version).
    """
    global cass_version, cql_version

    if cass_version is not None:
        return (cass_version, cql_version)

    c = Cluster()
    s = c.connect()
    row = s.execute('SELECT cql_version, release_version FROM system.local')[0]

    cass_version = _tuple_version(row.release_version)
    cql_version = _tuple_version(row.cql_version)

    c.shutdown()

    return (cass_version, cql_version)


def _tuple_version(version_string):
    if '-' in version_string:
        version_string = version_string[:version_string.index('-')]

    return tuple([int(p) for p in version_string.split('.')])


USE_CASS_EXTERNAL = bool(os.getenv('USE_CASS_EXTERNAL', False))

# If set to to true this will force the Cython tests to run regardless of whether they are installed
cython_env = os.getenv('VERIFY_CYTHON', "False")


VERIFY_CYTHON = False

if(cython_env == 'True'):
    VERIFY_CYTHON = True

default_cassandra_version = '2.2.0'


def _get_cass_version_from_dse(dse_version):
    if dse_version.startswith('4.6') or dse_version.startswith('4.5'):
        raise Exception("Cassandra Version 2.0 not supported anymore")
    elif dse_version.startswith('4.7') or dse_version.startswith('4.8'):
        cass_ver = "2.1"
    elif dse_version.startswith('5.0'):
        cass_ver = "3.0"
    elif dse_version.startswith('5.1'):
        cass_ver = "3.1"
    else:
        log.error("Uknown dse version found {0}, defaulting to 2.1".format(dse_version))
        cass_ver = "2.1"

    return cass_ver

DSE_IP = os.getenv('DSE_IP', '127.0.0.1')
CASSANDRA_DIR = os.getenv('CASSANDRA_DIR', None)
DSE_VERSION = os.getenv('DSE_VERSION', None)
DSE_CRED = os.getenv('DSE_CREDS', None)
if DSE_VERSION:
    CASSANDRA_VERSION = _get_cass_version_from_dse(DSE_VERSION)
else:
    CASSANDRA_VERSION = os.getenv('CASSANDRA_VERSION', default_cassandra_version)

CCM_KWARGS = {}
if CASSANDRA_DIR and (len(CASSANDRA_DIR) >= 1):
    log.info("Using Cassandra dir: %s", CASSANDRA_DIR)
    CCM_KWARGS['install_dir'] = CASSANDRA_DIR

else:
    log.info('Using Cassandra version: %s', CASSANDRA_VERSION)
    CCM_KWARGS['version'] = CASSANDRA_VERSION

if DSE_VERSION:
    log.info('Using DSE version: %s', DSE_VERSION)
    if not CASSANDRA_DIR:
        CCM_KWARGS['version'] = DSE_VERSION
        if DSE_CRED:
            log.info("Using DSE credentials file located at {0}".format(DSE_CRED))
            CCM_KWARGS['dse_credentials_file'] = DSE_CRED


#This changes the default contact_point parameter in Cluster
def set_default_dse_ip():
    if DSE_IP.startswith("127.0.0."):
        return
    defaults = list(Cluster.__init__.__defaults__)
    defaults = [[DSE_IP]] + defaults[1:]
    try:
        Cluster.__init__.__defaults__ = tuple(defaults)
    except:
        Cluster.__init__.__func__.__defaults__ = tuple(defaults)


def get_default_protocol():

    if Version(CASSANDRA_VERSION) >= Version('3.10') and DSE_VERSION:
        return ProtocolVersion.DSE_V1
    if Version(CASSANDRA_VERSION) >= Version('3.10'):
        return 5
    if Version(CASSANDRA_VERSION) >= Version('2.2'):
        return 4
    elif Version(CASSANDRA_VERSION) >= Version('2.1'):
        return 3
    elif Version(CASSANDRA_VERSION) >= Version('2.0'):
        raise Exception("Cassandra Version 2.0 not supported anymore")
    else:
        raise Exception("Running tests with an unsupported Cassandra version: {0}".format(CASSANDRA_VERSION))


def get_supported_protocol_versions():
    """
    1.2 -> 1
    2.0 -> 2, 1
    2.1 -> 3, 2, 1
    2.2 -> 4, 3, 2, 1
    3.X -> 4, 3
    3.10(C*) -> 5(beta),4,3
    3.10(DSE) -> DSE_V1,4,3
`   """
    if Version(CASSANDRA_VERSION) >= Version('3.10') and DSE_VERSION:
        return (3, 4, ProtocolVersion.DSE_V1)
    elif Version(CASSANDRA_VERSION) >= Version('3.10'):
        return (3, 4, 5)
    elif Version(CASSANDRA_VERSION) >= Version('3.0'):
        return (3, 4)
    elif Version(CASSANDRA_VERSION) >= Version('2.2'):
        return (3, 4)
    elif Version(CASSANDRA_VERSION) >= Version('2.1'):
        return (3, )
    elif Version(CASSANDRA_VERSION) >= Version('2.0'):
        raise Exception("Cassandra Version 2.0 not supported anymore")
    else:
        raise Exception("Cassandra Version not supported anymore")


def is_protocol_beta(protocol):
    if Version(CASSANDRA_VERSION) >= Version('3.10') and protocol == 5:
        return True
    else:
        return False


def get_unsupported_lower_protocol():
    """
    This is used to determine the lowest protocol version that is NOT
    supported by the version of C* running
    """
    #Right now all the Cassandra versions support protocol v3 which is the lowest version
    return None

def get_unsupported_upper_protocol():
    """
    This is used to determine the highest protocol version that is NOT
    supported by the version of C* running
    """

    if Version(CASSANDRA_VERSION) >= Version('2.2'):
        return None
    if Version(CASSANDRA_VERSION) >= Version('2.1'):
        return 4
    elif Version(CASSANDRA_VERSION) >= Version('2.0'):
        raise Exception("Cassandra Version 2.0 not supported anymore")
    else:
        return None

default_protocol_version = get_default_protocol()


PROTOCOL_VERSION = int(os.getenv('PROTOCOL_VERSION', default_protocol_version))


local = unittest.skipUnless(DSE_IP.startswith("127.0.0."), 'Tests only runs against local C*')
notprotocolv1 = unittest.skipUnless(PROTOCOL_VERSION > 1, 'Protocol v1 not supported')
lessthenprotocolv4 = unittest.skipUnless(PROTOCOL_VERSION < 4, 'Protocol versions 4 or greater not supported')
greaterthanprotocolv3 = unittest.skipUnless(PROTOCOL_VERSION >= 4, 'Protocol versions less than 4 are not supported')
protocolv5 = unittest.skipUnless(5 in get_supported_protocol_versions(), 'Protocol versions less than 5 are not supported')

greaterthancass21 = unittest.skipUnless(CASSANDRA_VERSION >= '2.2', 'Cassandra version 2.2 or greater required')
greaterthanorequalcass30 = unittest.skipUnless(CASSANDRA_VERSION >= '3.0', 'Cassandra version 3.0 or greater required')
greaterthanorequalcass31 = unittest.skipUnless(CASSANDRA_VERSION >= '3.1', 'Cassandra version 3.1 or greater required')
greaterthanorequalcass36 = unittest.skipUnless(CASSANDRA_VERSION >= '3.6', 'Cassandra version 3.6 or greater required')
lessthancass30 = unittest.skipUnless(CASSANDRA_VERSION < '3.0', 'Cassandra version less then 3.0 required')

greaterthanorequaldse51 = unittest.skipUnless(DSE_VERSION and DSE_VERSION >= '5.1', "DSE 5.1 or greater required for this test")
greaterthanorequaldse50 = unittest.skipUnless(DSE_VERSION and DSE_VERSION >= '5.0', "DSE 5.0 or greater required for this test")
lessthandse51 = unittest.skipUnless(DSE_VERSION and DSE_VERSION < '5.1', "DSE version less than 5.1 required")

pypy = unittest.skipUnless(platform.python_implementation() == "PyPy", "Test is skipped unless it's on PyPy")
notpy3 = unittest.skipIf(sys.version_info >= (3, 0), "Test not applicable for Python 3.x runtime")


def wait_for_node_socket(node, timeout):
    binary_itf = node.network_interfaces['binary']
    if not common.check_socket_listening(binary_itf, timeout=timeout):
        log.warn("Unable to connect to binary socket for node " + node.name)
    else:
        log.debug("Node %s is up and listening " % (node.name,))


def check_socket_listening(itf, timeout=60):
    end = time.time() + timeout
    while time.time() <= end:
        try:
            sock = socket.socket()
            sock.connect(itf)
            sock.close()
            return True
        except socket.error:
            # Try again in another 200ms
            time.sleep(.2)
            continue
    return False


def get_cluster():
    return CCM_CLUSTER


def get_node(node_id):
    return CCM_CLUSTER.nodes['node%s' % node_id]


def use_multidc(dc_list, workloads=[]):
    use_cluster(MULTIDC_CLUSTER_NAME, dc_list, start=True, workloads=workloads)


def use_singledc(start=True, workloads=[]):
    use_cluster(CLUSTER_NAME, [3], start=start, workloads=workloads)


def use_single_node(start=True, workloads=[]):
    use_cluster(SINGLE_NODE_CLUSTER_NAME, [1], start=start, workloads=workloads)


def remove_cluster():
    if USE_CASS_EXTERNAL:
        return

    global CCM_CLUSTER
    if CCM_CLUSTER:
        log.debug("Removing cluster {0}".format(CCM_CLUSTER.name))
        tries = 0
        while tries < 100:
            try:
                CCM_CLUSTER.remove()
                CCM_CLUSTER = None
                return
            except OSError:
                ex_type, ex, tb = sys.exc_info()
                log.warn("{0}: {1} Backtrace: {2}".format(ex_type.__name__, ex, traceback.extract_tb(tb)))
                del tb
                tries += 1
                time.sleep(1)

        raise RuntimeError("Failed to remove cluster after 100 attempts")


def is_current_cluster(cluster_name, node_counts, workloads):
    global CCM_CLUSTER
    if CCM_CLUSTER and CCM_CLUSTER.name == cluster_name:
        if [len(list(nodes)) for dc, nodes in
                groupby(CCM_CLUSTER.nodelist(), lambda n: n.data_center)] == node_counts:
            for node in CCM_CLUSTER.nodelist():
                if set(node.workloads) != set(workloads):
                    print("node workloads don't match creating new cluster")
                    return False
            return True
    return False

def start_cluster_wait_for_up(cluster):
    cluster.start(no_wait=True)
    # Added to wait for slow nodes to start up
    log.debug("Cluster started waiting for binary ports")
    for node in CCM_CLUSTER.nodes.values():
        wait_for_node_socket(node, 120)
    log.debug("Binary port are open")

def use_cluster(cluster_name, nodes, ipformat=None, start=True, workloads=[]):
    set_default_dse_ip()

    global CCM_CLUSTER
    if USE_CASS_EXTERNAL:
        if CCM_CLUSTER:
            log.debug("Using external CCM cluster {0}".format(CCM_CLUSTER.name))
        else:
            log.debug("Using unnamed external cluster")
        setup_keyspace(ipformat=ipformat, wait=False)
        return

    if is_current_cluster(cluster_name, nodes, workloads):
        log.debug("Using existing cluster, matching topology: {0}".format(cluster_name))
    else:
        if CCM_CLUSTER:
            log.debug("Stopping existing cluster, topology mismatch: {0}".format(CCM_CLUSTER.name))
            CCM_CLUSTER.stop()

        try:
            CCM_CLUSTER = CCMClusterFactory.load(path, cluster_name)
            log.debug("Found existing CCM cluster, {0}; clearing.".format(cluster_name))
            CCM_CLUSTER.clear()
            CCM_CLUSTER.set_install_dir(**CCM_KWARGS)
        except Exception:
            ex_type, ex, tb = sys.exc_info()
            log.warn("{0}: {1} Backtrace: {2}".format(ex_type.__name__, ex, traceback.extract_tb(tb)))
            del tb

            log.debug("Creating new CCM cluster, {0}, with args {1}".format(cluster_name, CCM_KWARGS))
            if DSE_VERSION:
                log.error("creating dse cluster")
                CCM_CLUSTER = DseCluster(path, cluster_name, **CCM_KWARGS)
            else:
                CCM_CLUSTER = CCMCluster(path, cluster_name, **CCM_KWARGS)
            CCM_CLUSTER.set_configuration_options({'start_native_transport': True})
            CCM_CLUSTER.set_configuration_options({'batch_size_warn_threshold_in_kb': 5})
            if CASSANDRA_VERSION >= '2.2':
                CCM_CLUSTER.set_configuration_options({'enable_user_defined_functions': True})
                if CASSANDRA_VERSION >= '3.0':
                    CCM_CLUSTER.set_configuration_options({'enable_scripted_user_defined_functions': True})
            if 'spark' in workloads:
                config_options = {"initial_spark_worker_resources": 0.1}
                CCM_CLUSTER.set_dse_configuration_options(config_options)
            common.switch_cluster(path, cluster_name)
            CCM_CLUSTER.populate(nodes, ipformat=ipformat)
    try:
        jvm_args = []
        # This will enable the Mirroring query handler which will echo our custom payload k,v pairs back

        if 'graph' not in workloads:
            if PROTOCOL_VERSION >= 4:
                jvm_args = [" -Dcassandra.custom_query_handler_class=org.apache.cassandra.cql3.CustomPayloadMirroringQueryHandler"]
        if(len(workloads) > 0):
            for node in CCM_CLUSTER.nodes.values():
                node.set_workloads(workloads)
        if start:
            log.debug("Starting CCM cluster: {0}".format(cluster_name))
            CCM_CLUSTER.start(no_wait=True, jvm_args=jvm_args)
            # Added to wait for slow nodes to start up
            log.debug("Cluster started waiting for binary ports")
            for node in CCM_CLUSTER.nodes.values():
                wait_for_node_socket(node, 120)
            log.debug("Binary port are open")
            setup_keyspace(ipformat=ipformat)
    except Exception:
        log.exception("Failed to start CCM cluster; removing cluster.")

        if os.name == "nt":
            if CCM_CLUSTER:
                for node in CCM_CLUSTER.nodes.itervalues():
                    os.system("taskkill /F /PID " + str(node.pid))
        else:
            call(["pkill", "-9", "-f", ".ccm"])
        remove_cluster()
        raise


def teardown_package():
    if USE_CASS_EXTERNAL:
        return
    # when multiple modules are run explicitly, this runs between them
    # need to make sure CCM_CLUSTER is properly cleared for that case
    remove_cluster()
    for cluster_name in [CLUSTER_NAME, MULTIDC_CLUSTER_NAME]:
        try:
            cluster = CCMClusterFactory.load(path, cluster_name)
            try:
                cluster.remove()
                log.info('Removed cluster: %s' % cluster_name)
            except Exception:
                log.exception('Failed to remove cluster: %s' % cluster_name)

        except Exception:
            log.warning('Did not find cluster: %s' % cluster_name)


def execute_until_pass(session, query):
    tries = 0
    while tries < 100:
        try:
            return session.execute(query)
        except (ConfigurationException, AlreadyExists, InvalidRequest):
            log.warn("Received already exists from query {0}   not exiting".format(query))
            # keyspace/table was already created/dropped
            return
        except (OperationTimedOut, ReadTimeout, ReadFailure, WriteTimeout, WriteFailure):
            ex_type, ex, tb = sys.exc_info()
            log.warn("{0}: {1} Backtrace: {2}".format(ex_type.__name__, ex, traceback.extract_tb(tb)))
            del tb
            tries += 1

    raise RuntimeError("Failed to execute query after 100 attempts: {0}".format(query))


def execute_with_long_wait_retry(session, query, timeout=30):
    tries = 0
    while tries < 10:
        try:
            return session.execute(query, timeout=timeout)
        except (ConfigurationException, AlreadyExists):
            log.warn("Received already exists from query {0}    not exiting".format(query))
            # keyspace/table was already created/dropped
            return
        except (OperationTimedOut, ReadTimeout, ReadFailure, WriteTimeout, WriteFailure):
            ex_type, ex, tb = sys.exc_info()
            log.warn("{0}: {1} Backtrace: {2}".format(ex_type.__name__, ex, traceback.extract_tb(tb)))
            del tb
            tries += 1

    raise RuntimeError("Failed to execute query after 100 attempts: {0}".format(query))


def execute_with_retry_tolerant(session, query, retry_exceptions, escape_exception):
    # TODO refactor above methods into this one for code reuse
    tries = 0
    while tries < 100:
        try:
            tries += 1
            rs = session.execute(query)
            return rs
        except escape_exception:
            return
        except retry_exceptions:
            time.sleep(.1)

    raise RuntimeError("Failed to execute query after 100 attempts: {0}".format(query))


def drop_keyspace_shutdown_cluster(keyspace_name, session, cluster):
    try:
        execute_with_long_wait_retry(session, "DROP KEYSPACE {0}".format(keyspace_name))
    except:
        log.warn("Error encountered when droping keyspace {0}".format(keyspace_name))
        ex_type, ex, tb = sys.exc_info()
        log.warn("{0}: {1} Backtrace: {2}".format(ex_type.__name__, ex, traceback.extract_tb(tb)))
        del tb
    finally:
        log.warn("Shutting down cluster")
        cluster.shutdown()


def setup_keyspace(ipformat=None, wait=True):
    # wait for nodes to startup
    if wait:
        time.sleep(10)

    if not ipformat:
        cluster = Cluster(protocol_version=PROTOCOL_VERSION)
    else:
        cluster = Cluster(contact_points=["::1"], protocol_version=PROTOCOL_VERSION)
    session = cluster.connect()

    try:
        for ksname in ('test1rf', 'test2rf', 'test3rf'):
            if ksname in cluster.metadata.keyspaces:
                execute_until_pass(session, "DROP KEYSPACE %s" % ksname)

        ddl = '''
            CREATE KEYSPACE test3rf
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '3'}'''
        execute_with_long_wait_retry(session, ddl)

        ddl = '''
            CREATE KEYSPACE test2rf
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '2'}'''
        execute_with_long_wait_retry(session, ddl)

        ddl = '''
            CREATE KEYSPACE test1rf
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '1'}'''
        execute_with_long_wait_retry(session, ddl)

        ddl = '''
            CREATE TABLE test3rf.test (
                k int PRIMARY KEY,
                v int )'''
        execute_with_long_wait_retry(session, ddl)

    except Exception:
        traceback.print_exc()
        raise
    finally:
        cluster.shutdown()


class UpDownWaiter(object):

    def __init__(self, host):
        self.down_event = Event()
        self.up_event = Event()
        host.monitor.register(self)

    def on_up(self, host):
        self.up_event.set()

    def on_down(self, host):
        self.down_event.set()

    def wait_for_down(self):
        self.down_event.wait()

    def wait_for_up(self):
        self.up_event.wait()


class BasicKeyspaceUnitTestCase(unittest.TestCase):
    """
    This is basic unit test case that provides various utility methods that can be leveraged for testcase setup and tear
    down
    """
    @property
    def keyspace_name(self):
        return self.ks_name

    @property
    def class_table_name(self):
        return self.ks_name

    @property
    def function_table_name(self):
        return self._testMethodName.lower()

    @property
    def keyspace_table_name(self):
        return "{0}.{1}".format(self.keyspace_name, self._testMethodName.lower())

    @classmethod
    def drop_keyspace(cls):
        execute_with_long_wait_retry(cls.session, "DROP KEYSPACE {0}".format(cls.ks_name))

    @classmethod
    def create_keyspace(cls, rf):
        ddl = "CREATE KEYSPACE {0} WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': '{1}'}}".format(cls.ks_name, rf)
        execute_with_long_wait_retry(cls.session, ddl)

    @classmethod
    def common_setup(cls, rf, keyspace_creation=True, create_class_table=False, **cluster_kwargs):
        cls.cluster = Cluster(protocol_version=PROTOCOL_VERSION, **cluster_kwargs)
        cls.session = cls.cluster.connect(wait_for_all_pools=True)
        cls.ks_name = cls.__name__.lower()
        if keyspace_creation:
            cls.create_keyspace(rf)
        cls.cass_version, cls.cql_version = get_server_versions()

        if create_class_table:

            ddl = '''
                CREATE TABLE {0}.{1} (
                    k int PRIMARY KEY,
                    v int )'''.format(cls.ks_name, cls.ks_name)
            execute_until_pass(cls.session, ddl)

    def create_function_table(self):
            ddl = '''
                CREATE TABLE {0}.{1} (
                    k int PRIMARY KEY,
                    v int )'''.format(self.keyspace_name, self.function_table_name)
            execute_until_pass(self.session, ddl)

    def drop_function_table(self):
            ddl = "DROP TABLE {0}.{1} ".format(self.keyspace_name, self.function_table_name)
            execute_until_pass(self.session, ddl)


class MockLoggingHandler(logging.Handler):
    """Mock logging handler to check for expected logs."""

    def __init__(self, *args, **kwargs):
        self.reset()
        logging.Handler.__init__(self, *args, **kwargs)

    def emit(self, record):
        self.messages[record.levelname.lower()].append(record.getMessage())

    def reset(self):
        self.messages = {
            'debug': [],
            'info': [],
            'warning': [],
            'error': [],
            'critical': [],
        }

    def get_message_count(self, level, sub_string):
        count = 0
        for msg in self.messages.get(level):
            if sub_string in msg:
                count+=1
        return count


class BasicExistingKeyspaceUnitTestCase(BasicKeyspaceUnitTestCase):
    """
    This is basic unit test defines class level teardown and setup methods. It assumes that keyspace is already defined, or created as part of the test.
    """
    @classmethod
    def setUpClass(cls):
        cls.common_setup(1, keyspace_creation=False)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.shutdown()


class BasicSharedKeyspaceUnitTestCase(BasicKeyspaceUnitTestCase):
    """
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the testclass with a rf of 1.
    """
    @classmethod
    def setUpClass(cls):
        cls.common_setup(1)

    @classmethod
    def tearDownClass(cls):
        drop_keyspace_shutdown_cluster(cls.ks_name, cls.session, cls.cluster)


class BasicSharedKeyspaceUnitTestCaseWTable(BasicSharedKeyspaceUnitTestCase):
    """
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the testclass with a rf of 1, and a table named after the class
    """
    @classmethod
    def setUpClass(self):
        self.common_setup(1, True)


class BasicSharedKeyspaceUnitTestCaseRF2(BasicSharedKeyspaceUnitTestCase):
    """
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the test class with a rf of 2, and a table named after the class
    """
    @classmethod
    def setUpClass(self):
        self.common_setup(2)


class BasicSharedKeyspaceUnitTestCaseWTable(BasicSharedKeyspaceUnitTestCase):
    """
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the testc lass with a rf of 2, and a table named after the class
    """
    @classmethod
    def setUpClass(self):
        self.common_setup(3, True, True, metrics_enabled=True)


class BasicSharedKeyspaceUnitTestCaseRF3(BasicSharedKeyspaceUnitTestCase):
    """
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the test class with a rf of 3
    """
    @classmethod
    def setUpClass(self):
        self.common_setup(3)


class BasicSharedKeyspaceUnitTestCaseRF3WTable(BasicSharedKeyspaceUnitTestCase):
    """
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the test class with a rf of 3 and a table named after the class
    """
    @classmethod
    def setUpClass(self):
        self.common_setup(3, True, True)


class BasicSharedKeyspaceUnitTestCaseWFunctionTable(BasicSharedKeyspaceUnitTestCase):
    """"
    This is basic unit test case that can be leveraged to scope a keyspace to a specific test class.
    creates a keyspace named after the test class with a rf of 3 and a table named after the class
    the table is scoped to just the unit test and will be removed.

    """
    def setUp(self):
        self.create_function_table()

    def tearDown(self):
        self.drop_function_table()


class BasicSegregatedKeyspaceUnitTestCase(BasicKeyspaceUnitTestCase):
    """
    This unit test will create and teardown a keyspace for each individual unit tests.
    It has overhead and should only be used with complex unit test were sharing a keyspace will
    cause issues.
    """
    def setUp(self):
        self.common_setup(1)

    def tearDown(self):
        drop_keyspace_shutdown_cluster(self.ks_name, self.session, self.cluster)


class BasicExistingSegregatedKeyspaceUnitTestCase(BasicKeyspaceUnitTestCase):
    """
    This unit test will create and teardown or each individual unit tests. It assumes that keyspace is existing
    or created as part of a test.
    It has some overhead and should only be used when sharing cluster/session is not feasible.
    """
    def setUp(self):
        self.common_setup(1, keyspace_creation=False)

    def tearDown(self):
        self.cluster.shutdown()
