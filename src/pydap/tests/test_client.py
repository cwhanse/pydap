"""Test the Pydap client."""

import os
import sys
if sys.version_info < (2, 7):
    import unittest2 as unittest
else:
    import unittest

import numpy as np
from webtest import TestApp
import requests

from pydap.model import *
from pydap.handlers.lib import BaseHandler
from pydap.client import open_url, open_dods, open_file, Functions
from pydap.tests import requests_intercept
from pydap.tests.datasets import SimpleSequence, SimpleGrid
from pydap.wsgi.ssf import ServerSideFunctions


DODS = os.path.join(os.path.dirname(__file__), 'test.01.dods')
DAS = os.path.join(os.path.dirname(__file__), 'test.01.das')


class TestOpenUrl(unittest.TestCase):

    """Test the ``open_url`` function, to access remote datasets."""

    def setUp(self):
        """Create a WSGI app and monkeypatch ``requests`` for direct access."""
        app = TestApp(BaseHandler(SimpleSequence))
        self.requests_get = requests.get
        requests.get = requests_intercept(app, 'http://localhost:8001/')

    def tearDown(self):
        """Return method to its original version."""
        requests.get = self.requests_get

    def test_open_url(self):
        """Open an URL and check dataset keys."""
        dataset = open_url('http://localhost:8001/')
        self.assertEqual(dataset.keys(), ["cast"])


class TestOpenFile(unittest.TestCase):

    """Test the ``open_file`` function, to read downloaded files."""

    def test_open_dods(self):
        """Open a file downloaded from the test server with the DAS."""
        dataset = open_file(DODS)

        # test data
        self.assertEqual(dataset.data, [
            0, 1, 0, 0, 0, 0.0, 1000.0,
            'This is a data test string (pass 0).',
            'http://www.dods.org',
        ])

        # test attributes
        self.assertEqual(dataset.attributes, {})
        self.assertEqual(dataset.i32.attributes, {})
        self.assertEqual(dataset.b.attributes, {})

    def test_open_dods_das(self):
        """Open a file downloaded from the test server with the DAS."""
        dataset = open_file(DODS, DAS)

        # test data
        self.assertEqual(dataset.data, [
            0, 1, 0, 0, 0, 0.0, 1000.0,
            'This is a data test string (pass 0).',
            'http://www.dods.org',
        ])

        # test attributes
        self.assertEqual(dataset.i32.units, 'unknown')
        self.assertEqual(dataset.i32.Description, 'A 32 bit test server int')
        self.assertEqual(dataset.b.units, 'unknown')
        self.assertEqual(dataset.b.Description, 'A test byte')
        self.assertEqual(
            dataset.Facility['DataCenter'],
            "COAS Environmental Computer Facility")
        self.assertEqual(
            dataset.Facility['PrincipleInvestigator'],
            ['Mark Abbott', 'Ph.D'])
        self.assertEqual(
            dataset.Facility['DrifterType'],
            "MetOcean WOCE/OCM")


class TestOpenDods(unittest.TestCase):

    """Test the ``open_dods`` function, to access binary data directly."""

    def setUp(self):
        """Create a WSGI app and monkeypatch ``requests`` for direct access."""
        app = TestApp(BaseHandler(SimpleSequence))
        self.requests_get = requests.get
        requests.get = requests_intercept(app, 'http://localhost:8001/')

    def tearDown(self):
        """Return method to its original version."""
        requests.get = self.requests_get

    def test_open_dods(self):
        """Open the dods response from a server.

        Note that here we cannot simply compare ``dataset.data`` with the
        original data ``SimpleSequence.data``, because the original data
        contains int16 values which are transmitted as int32 in the DAP spec.

        """
        dataset = open_dods('http://localhost:8001/.dods')
        np.testing.assert_array_equal(
            dataset.data,
            np.array([[
                ('1', 100, -10, 0, -1, 21, 35, 0),
                ('2', 200, 10, 500, 1, 15, 35, 100)]],
                dtype=[
                    ('id', 'S1'), ('lon', '<i4'), ('lat', '<i4'),
                    ('depth', '<i4'), ('time', '<i4'), ('temperature', '<i4'),
                    ('salinity', '<i4'), ('pressure', '<i4')]))

        # attributes should be empty
        self.assertEqual(dataset.attributes, {})

    def test_open_dods_with_attributes(self):
        """Open the dods response together with the dsa response."""
        dataset = open_dods('http://localhost:8001/.dods', metadata=True)
        self.assertEqual(dataset.NC_GLOBAL, {})
        self.assertEqual(dataset.DODS_EXTRA, {})
        self.assertEqual(
            dataset.description, "A simple sequence for testing.")
        self.assertEqual(dataset.cast.lon.axis, 'X')
        self.assertEqual(dataset.cast.lat.axis, 'Y')
        self.assertEqual(dataset.cast.depth.axis, 'Z')
        self.assertEqual(dataset.cast.time.axis, 'T')
        self.assertEqual(
            dataset.cast.time.units, "days since 1970-01-01")


class TestFunctions(unittest.TestCase):

    """Test the local implementation of server-side functions.

    Calling server-side functions is implemented using a lazy mechanism where
    arbitrary names are mapped to remove calls. The resulting dataset is only
    evaluated when ``__getitem__`` or ``__getattr__`` are called, allowing
    nested calls to be evaluated only once:

        >>> dataset = functions.mean(functions.mean(remote.SimpleGrid, 0), 0)

    In this example the nested calls to ``mean`` will return a single proxy
    object.

    """

    def setUp(self):
        """Create a WSGI app and monkeypatch ``requests`` for direct access."""
        app = TestApp(ServerSideFunctions(BaseHandler(SimpleGrid)))
        self.requests_get = requests.get
        requests.get = requests_intercept(app, 'http://localhost:8001/')

    def tearDown(self):
        """Return method to its original version."""
        requests.get = self.requests_get

    def test_original(self):
        """Test an unmodified call, without function calls."""
        original = open_url('http://localhost:8001/')
        self.assertEqual(original.SimpleGrid.SimpleGrid.shape, (2, 3))

    def test_first_axis(self):
        """Test mean over the first axis."""
        original = open_url('http://localhost:8001/')
        dataset = original.functions.mean(original.SimpleGrid, 0)
        self.assertEqual(dataset.SimpleGrid.SimpleGrid.shape, (3,))
        np.testing.assert_array_equal(
            dataset.SimpleGrid.SimpleGrid.data,
            np.array([1.5, 2.5, 3.5]))

    def test_second_axis(self):
        """Test mean over the second axis."""
        original = open_url('http://localhost:8001/')
        dataset = original.functions.mean(original.SimpleGrid, 1)
        self.assertEqual(dataset.SimpleGrid.SimpleGrid.shape, (2,))
        np.testing.assert_array_equal(
            dataset.SimpleGrid.SimpleGrid.data,
            np.array([1.0, 4.0]))

    def test_lazy_evaluation_getitem(self):
        """Test that the dataset is only loaded when accessed."""
        original = open_url('http://localhost:8001/')
        dataset = original.functions.mean(original.SimpleGrid, 0)
        self.assertIsNone(dataset.dataset)
        dataset['SimpleGrid']
        self.assertIsNotNone(dataset.dataset)

    def test_lazy_evaluation_getattr(self):
        """Test that the dataset is only loaded when accessed."""
        original = open_url('http://localhost:8001/')
        dataset = original.functions.mean(original.SimpleGrid, 0)
        self.assertIsNone(dataset.dataset)
        dataset.SimpleGrid
        self.assertIsNotNone(dataset.dataset)

    def test_nested_call(self):
        """Test nested calls."""
        original = open_url('http://localhost:8001/')
        dataset = original.functions.mean(
            original.functions.mean(original.SimpleGrid, 0), 0)
        self.assertEqual(dataset['SimpleGrid']['SimpleGrid'].shape, ())
        np.testing.assert_array_equal(
            dataset.SimpleGrid.SimpleGrid.data,
            np.array(2.5))

    def test_axis_mean(self):
        """Test the mean over an axis, returning a scalar."""
        original = open_url('http://localhost:8001/')
        dataset = original.functions.mean(original.SimpleGrid.x)
        self.assertEqual(dataset.x.shape, ())
        np.testing.assert_array_equal(
            dataset.x.data,
            np.array(1.0))
