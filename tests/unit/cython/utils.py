# Copyright 2016 DataStax, Inc.
#
# Licensed under the DataStax DSE Driver License;
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
# http://www.datastax.com/terms/datastax-dse-driver-license-terms

from dse.cython_deps import HAVE_CYTHON, HAVE_NUMPY
from tests.integration import VERIFY_CYTHON

try:
    import unittest2 as unittest
except ImportError:
    import unittest  # noqa

def cyimport(import_path):
    """
    Import a Cython module if available, otherwise return None
    (and skip any relevant tests).
    """
    if HAVE_CYTHON:
        import pyximport
        py_importer, pyx_importer = pyximport.install()
        mod = __import__(import_path, fromlist=[True])
        pyximport.uninstall(py_importer, pyx_importer)
        return mod


# @cythontest
# def test_something(self): ...
cythontest = unittest.skipUnless((HAVE_CYTHON or VERIFY_CYTHON) or VERIFY_CYTHON, 'Cython is not available')
notcython = unittest.skipIf(HAVE_CYTHON, 'Cython not supported')
numpytest = unittest.skipUnless((HAVE_CYTHON and HAVE_NUMPY) or VERIFY_CYTHON, 'NumPy is not available')