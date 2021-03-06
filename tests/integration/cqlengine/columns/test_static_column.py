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

from uuid import uuid4

from dse.cqlengine import columns
from dse.cqlengine.management import sync_table, drop_table
from dse.cqlengine.models import Model

from tests.integration.cqlengine.base import BaseCassEngTestCase

class TestStaticModel(Model):
    partition = columns.UUID(primary_key=True, default=uuid4)
    cluster = columns.UUID(primary_key=True, default=uuid4)
    static = columns.Text(static=True)
    text = columns.Text()


class TestStaticColumn(BaseCassEngTestCase):

    def setUp(cls):
        super(TestStaticColumn, cls).setUp()

    @classmethod
    def setUpClass(cls):
        drop_table(TestStaticModel)
        sync_table(TestStaticModel)

    @classmethod
    def tearDownClass(cls):
        drop_table(TestStaticModel)

    def test_mixed_updates(self):
        """ Tests that updates on both static and non-static columns work as intended """
        instance = TestStaticModel.create()
        instance.static = "it's shared"
        instance.text = "some text"
        instance.save()

        u = TestStaticModel.get(partition=instance.partition)
        u.static = "it's still shared"
        u.text = "another text"
        u.update()
        actual = TestStaticModel.get(partition=u.partition)

        assert actual.static == "it's still shared"

    def test_static_only_updates(self):
        """ Tests that updates on static only column work as intended """
        instance = TestStaticModel.create()
        instance.static = "it's shared"
        instance.text = "some text"
        instance.save()

        u = TestStaticModel.get(partition=instance.partition)
        u.static = "it's still shared"
        u.update()
        actual = TestStaticModel.get(partition=u.partition)
        assert actual.static == "it's still shared"

    def test_static_with_null_cluster_key(self):
        """ Tests that save/update/delete works for static column works when clustering key is null"""
        instance = TestStaticModel.create(cluster=None, static = "it's shared")
        instance.save()

        u = TestStaticModel.get(partition=instance.partition)
        u.static = "it's still shared"
        u.update()
        actual = TestStaticModel.get(partition=u.partition)
        assert actual.static == "it's still shared"
