# Copyright 2016 DataStax, Inc.
import time
from tests.integration import BasicGraphUnitTestCase, use_single_node_with_graph

import json

from cassandra import OperationTimedOut
from cassandra.protocol import ServerError
from cassandra.query import QueryTrace
from dse.graph import SimpleGraphStatement, graph_result_row_factory, Result, single_object_row_factory


def setup_module():
    use_single_node_with_graph()


class BasicGraphTest(BasicGraphUnitTestCase):

    def test_basic_query(self):
        """
        Test to validate that basic graph query results can be executed with a sane result set.

        Creates a simple classic tinkerpot graph, and attempts to find all vertices
        related the vertex marco, that have a label of knows.
        See reference graph here
        http://www.tinkerpop.com/docs/3.0.0.M1/

        @since 1.0.0
        @jira_ticket PYTHON-457
        @expected_result graph should find two vertices related to marco via 'knows' edges.

        @test_category dse graph
        """

        self._generate_classic()
        rs = self.session.execute_graph('''g.V().has('name','marko').out('knows').values('name')''')
        self.assertFalse(rs.has_more_pages)
        results_list = [result.value for result in rs.current_rows]
        self.assertEqual(len(results_list), 2)
        self.assertIn('vadas', results_list)
        self.assertIn('josh', results_list)

    def test_classic_graph(self):
        """
        Test to validate that basic graph generation, and vertex and edges are surfaced correctly

        Creates a simple classic tinkerpot graph, and iterates over the the vertices and edges
        ensureing that each one is correct. See reference graph here
        http://www.tinkerpop.com/docs/3.0.0.M1/

        @since 1.0.0
        @jira_ticket PYTHON-457
        @expected_result graph should generate and all vertices and edge results should be

        @test_category dse graph
        """
        self._generate_classic()
        rs = self.session.execute_graph('g.V()')
        for vertex in rs:
            self._validate_classic_vertex(vertex)
        rs = self.session.execute_graph('g.E()')
        for edge in rs:
            self._validate_classic_edge(edge)

    def test_graph_classic_path(self):
        """
        Test to validate that the path version of the result type is generated correctly. It also
        tests basic path results as that is not covered elsewhere

        @since 1.0.0
        @jira_ticket PYTHON-479
        @expected_result path object should be unpacked correctly including all nested edges and verticies
        @test_category dse graph
        """
        self._generate_classic()

        rs = self.session.execute_graph("g.V().hasLabel('person').has('name', 'marko').as('a')" +
            ".outE('knows').inV().as('c', 'd').outE('created').as('e', 'f', 'g').inV().path()");
        rs_list = list(rs)
        self.assertEqual(len(rs_list), 2)
        for result in rs_list:
            path = result.as_path()
            self._validate_path_result_type(path)

    def test_large_create_script(self):
        """
        Test to validate that server errors due to large groovy scripts are properly surfaced

        Creates a very large line graph script and executes it. Then proceeds to create a line graph script
        that is to large for the server to handle expects a server error to be returned

        @since 1.0.0
        @jira_ticket PYTHON-457
        @expected_result graph should generate and all vertices and edge results should be

        @test_category dse graph
        """
        query_to_run = self._generate_line_graph(900)
        self.session.execute_graph(query_to_run)
        query_to_run = self._generate_line_graph(950)
        self.assertRaises(ServerError, self.session.execute_graph, query_to_run)

    def test_range_query(self):
        """
        Test to validate range queries are handled correctly.

        Creates a very large line graph script and executes it. Then proceeds to to a range
        limited query against it, and ensure that the results are formated correctly and that
        the result set is properly sized.

        @since 1.0.0
        @jira_ticket PYTHON-457
        @expected_result result set should be properly formated and properly sized

        @test_category dse graph
        """
        query_to_run = self._generate_line_graph(900)
        self.session.execute_graph(query_to_run)
        rs = self.session.execute_graph("g.E().range(0,10)")
        self.assertFalse(rs.has_more_pages)
        self.assertEqual(len(rs.current_rows), 10)
        for result in rs:
            self._validate_line_edge(result)

    def test_result_types(self):
        """
        Test to validate that the edge and vertex version of results are constructed correctly.

        @since 1.0.0
        @jira_ticket PYTHON-479
        @expected_result edge/vertex result types should be unpacked correctly.
        @test_category dse graph
        """
        self._generate_multi_field_graph()

        rs = self.session.execute_graph("g.V()")

        for result in rs:
            self._validate_type(result)

    def test_large_result_set(self):
        """
        Test to validate that large result sets return correctly.

        Creates a very large graph. Ensures that large result sets are handled appropriately.

        @since 1.0.0
        @jira_ticket PYTHON-457
        @expected_result when limits of result sets are hit errors should be surfaced appropriately

        @test_category dse graph
        """
        self._generate_large_complex_graph(5000)
        rs = self.session.execute_graph("g.V()")
        for result in rs:
            self._validate_generic_vertex_values_exist(result)

    def test_parameter_passing(self):
        """
        Test to validate that parameter passing works as expected

        @since 1.0.0
        @jira_ticket PYTHON-457
        @expected_result parameters work as expected

        @test_category dse graph
        """

        s = self.session
        # unused parameters are passed, but ignored
        s.execute_graph("null", {"doesn't": "matter", "what's": "passed"})

        # multiple params
        results = s.execute_graph("[a, b]", {'a': 0, 'b': 1})
        self.assertEqual(results[0].value, 0)
        self.assertEqual(results[1].value, 1)

        # different value types
        for param in (None, "string", 1234, 5.678, True, False):
            result = s.execute_graph('x', {'x': param})[0]
            self.assertEqual(result.value, param)

    def test_geometric_graph_types(self):
        """
        Test to validate that geometric types function correctly

        Creates a very simple graph, and tries to insert a simple point type

        @since 1.0.0
        @jira_ticket DSP-8087
        @expected_result json types assoicated with insert is parsed correctly

        @test_category dse graph
        """
        results = self.session.execute_graph('''import org.apache.cassandra.db.marshal.geometry.Point;
                                    Schema schema = graph.schema();
                                    schema.buildVertexLabel('PointV').add();
                                    schema.buildPropertyKey('pointP', Point.class).add();''')
        rs = self.session.execute_graph('''g.addV(label, 'PointV', 'pointP', 'POINT(0 1)');''')
        # if result set is not parsed correctly this will throw an exception
        self.assertIsNotNone(rs)

    def test_result_forms(self):
        """
        Test to validate that geometric types function correctly

        Creates a very simple graph, and tries to insert a simple point type

        @since 1.0.0
        @jira_ticket DSP-8087
        @expected_result json types assoicated with insert is parsed correctly

        @test_category dse graph
        """
        self._generate_classic()
        rs = list(self.session.execute_graph('g.V()'))
        self.assertGreater(len(rs),0, "Result set was empty this was not expected")
        for vertex in rs:
            vertex_result = vertex.as_vertex()
            self._validate_classic_vertex_return_type(vertex_result)

        rs = list(self.session.execute_graph('g.E()'))
        self.assertGreater(len(rs),0, "Result set was empty this was not expected")
        for edge in rs:
            edge_result = edge.as_edge()
            self._validate_classic_edge_return_type(edge_result)

    def test_statement_graph_options(self):
        s = self.session
        statement = SimpleGraphStatement("true")
        statement.options.graph_name = self.graph_name
        self.assertTrue(s.execute_graph(statement)[0].value)

        # bad graph name to verify it's passed
        statement.options.graph_name = "definitely_not_correct"
        self.assertRaises(ServerError, s.execute_graph, statement)

        # removing makes it use the correct default
        del statement.options.graph_name
        self.assertTrue(s.execute_graph(statement)[0].value)

        # set a different alias
        statement = SimpleGraphStatement("x.V()")
        self.assertRaises(ServerError, s.execute_graph, statement)
        statement.options.graph_alias = 'x'
        s.execute_graph(statement)

    def test_execute_graph_timeout(self):
        s = self.session

        value = [1, 2, 3]
        query = "[%r]" % (value,)

        # default is passed down
        rs = s.execute_graph(query)
        self.assertEqual(rs[0].value, value)
        self.assertEqual(rs.response_future.timeout, s.default_graph_timeout)

        # tiny timeout times out as expected
        self.assertRaises(OperationTimedOut, s.execute_graph, query, timeout=0.0001)

    def test_execute_graph_trace(self):
        s = self.session

        value = [1, 2, 3]
        query = "[%r]" % (value,)

        # default is no trace
        rs = s.execute_graph(query)
        self.assertEqual(rs[0].value, value)
        self.assertIsNone(rs.get_query_trace())

        # request trace
        rs = s.execute_graph(query, trace=True)
        self.assertEqual(rs[0].value, value)
        qt = rs.get_query_trace(max_wait_sec=10)
        self.assertIsInstance(qt, QueryTrace)
        self.assertIsNotNone(qt.duration)

    def test_execute_graph_row_factory(self):
        s = self.session

        # default Results
        self.assertEqual(s.default_graph_row_factory, graph_result_row_factory)
        result = s.execute_graph("123")[0]
        self.assertIsInstance(result, Result)
        self.assertEqual(result.value, 123)

        # other via parameter
        rs = s.execute_graph("123", row_factory=single_object_row_factory)
        self.assertEqual(rs.response_future.row_factory, single_object_row_factory)
        self.assertEqual(json.loads(rs[0]), {'result': 123})

    def _validate_type(self, vertex):
        values = vertex.properties.values()
        for value in values:
            type_indicator = value[0].get('id').get('~type')
            if type_indicator.startswith('int'):
                actual_value = value[0].get('value')
                self.assertTrue(isinstance(actual_value, int))
            elif type_indicator.startswith('short'):
                actual_value = value[0].get('value')
                self.assertTrue(isinstance(actual_value, int))
            elif type_indicator.startswith('long'):
                actual_value = value[0].get('value')
                self.assertTrue(isinstance(actual_value, int))
            elif type_indicator.startswith('float'):
                actual_value = value[0].get('value')
                self.assertTrue(isinstance(actual_value, float))
            elif type_indicator.startswith('double'):
                actual_value = value[0].get('value')
                self.assertTrue(isinstance(actual_value, float))

    def _validate_classic_vertex(self, vertex):
        vertex_props = vertex.properties.keys()
        self.assertEqual(len(vertex_props), 2)
        self.assertIn('name', vertex_props)
        self.assertTrue('lang' in vertex_props or 'age' in vertex_props)

    def _validate_classic_vertex_return_type(self, vertex_obj):
        self._validate_generic_vertex_result_type(vertex_obj)
        vertex_props = vertex_obj.properties
        self.assertIn('name', vertex_props)
        self.assertTrue('lang' in vertex_props or 'age' in vertex_props)

    def _validate_generic_vertex_values_exist(self, vertex):
        value_map = vertex.value
        self.assertIn('properties', value_map)
        self.assertIn('type', value_map)
        self.assertIn('id', value_map)
        self.assertIn('label', value_map)
        self.assertIn('type', value_map)

    def _validate_generic_vertex_result_type(self, vertex_obj):
        self.assertIsNotNone(vertex_obj.id)
        self.assertIsNotNone(vertex_obj.type)
        self.assertIsNotNone(vertex_obj.label)
        self.assertIsNotNone(vertex_obj.properties)

    def _validate_classic_edge_properties(self, edge_properties):
        self.assertEqual(len(edge_properties.keys()), 1)
        self.assertIn('weight', edge_properties)

    def _validate_classic_edge_return_type(self, edge_obj):
        self._validate_generic_edge_result_type(edge_obj)
        self._validate_classic_edge_properties(edge_obj.properties)

    def _validate_classic_edge(self, edge):
        self._validate_classic_edge_properties(edge.properties)
        self._validate_generic_edge_values_exist(edge)

    def _validate_line_edge(self, edge):
        edge_props = edge.properties
        self.assertEqual(len(edge_props.keys()), 1)
        self.assertIn('distance', edge_props)
        self._validate_generic_edge_values_exist(edge)

    def _validate_generic_edge_values_exist(self, edge):
        value_map = edge.value
        self.assertIn('properties', value_map)
        self.assertIn('outV', value_map)
        self.assertIn('outVLabel', value_map)
        self.assertIn('inV', value_map)
        self.assertIn('inVLabel', value_map)
        self.assertIn('label', value_map)
        self.assertIn('type', value_map)
        self.assertIn('id', value_map)

    def _validate_generic_edge_result_type(self, edge_obj):
        self.assertIsNotNone(edge_obj.properties)
        self.assertIsNotNone(edge_obj.outV)
        self.assertIsNotNone(edge_obj.outVLabel)
        self.assertIsNotNone(edge_obj.inV)
        self.assertIsNotNone(edge_obj.inVLabel)
        self.assertIsNotNone(edge_obj.id)
        self.assertIsNotNone(edge_obj.type)
        self.assertIsNotNone(edge_obj.label)

    def _validate_path_result_type(self, path_obj):
        self.assertIsNotNone(path_obj.labels)
        for object in path_obj.objects:
            if(object.type == 'edge'):
                self._validate_classic_edge_return_type(object)
            elif(object.type == 'vertex'):
                self._validate_classic_vertex_return_type(object)
            else:
                self.fail("Invalid object found in path "+ str(object.type))

    def _generate_classic(self):
        to_run=['''graph.schema().buildVertexLabel('person').add()''',
                '''graph.schema().buildVertexLabel('software').add()''',
                '''graph.schema().buildEdgeLabel('created').add()''',
                '''graph.schema().buildPropertyKey('name', String.class).add()''',
                '''graph.schema().buildPropertyKey('age', Integer.class).add()''',
                '''graph.schema().buildPropertyKey('lang', String.class).add()''',
                '''graph.schema().buildPropertyKey('weight', Float.class).add()''',
                '''Vertex marko = graph.addVertex(label, 'person', 'name', 'marko', 'age', 29);
                Vertex vadas = graph.addVertex(label, 'person', 'name', 'vadas', 'age', 27);
                Vertex lop = graph.addVertex(label, 'software', 'name', 'lop', 'lang', 'java');
                Vertex josh = graph.addVertex(label, 'person', 'name', 'josh', 'age', 32);
                Vertex ripple = graph.addVertex(label, 'software', 'name', 'ripple', 'lang', 'java');
                Vertex peter = graph.addVertex(label, 'person', 'name', 'peter', 'age', 35);
                marko.addEdge('knows', vadas, 'weight', 0.5f);
                marko.addEdge('knows', josh, 'weight', 1.0f);
                marko.addEdge('created', lop, 'weight', 0.4f);
                josh.addEdge('created', ripple, 'weight', 1.0f);
                josh.addEdge('created', lop, 'weight', 0.4f);
                peter.addEdge('created', lop, 'weight', 0.2f);''']

        for run in to_run:
            self.session.execute_graph(run)

    def _generate_line_graph(self, length):
        query_parts = []
        for index in range(0, length):
            query_parts.append('''Vertex vertex{0} = graph.addVertex("index", {0}); '''.format(index))
            if index is not 0:
                query_parts.append('''vertex{0}.addEdge("goesTo", vertex{1}, "distance", 5); '''.format(index-1,index))
        final_graph_generation_statement = "".join(query_parts)
        return final_graph_generation_statement

    def _generate_multi_field_graph(self):
        to_run= ['''short s1 = 5000; graph.addVertex(label, "shortvertex", "shortvalue", s1);''',
                 '''int i1 = 1000000000; graph.addVertex(label, "intvertex", "intvalue", i1);''',
                 '''Integer i2 = 100000000; graph.addVertex(label, "intvertex2", "intvalue2", i2);''',
                 '''long l1 = 9223372036854775807; graph.addVertex(label, "longvertex", "longvalue", l1);''',
                 '''Long l2 = 100000000000000000L; graph.addVertex(label, "longvertex2", "longvalue2", l2);''',
                 '''float f1 = 3.5f; graph.addVertex(label, "floatvertex", "floatvalue", f1);''',
                 '''double d1 = 3.5e40; graph.addVertex(label, "doublevertex", "doublevalue", d1);''',
                 '''Double d2 = 3.5e40d; graph.addVertex(label, "doublevertex2", "doublevalue2", d2);''']

        for run in to_run:
            self.session.execute_graph(run)


    def _generate_large_complex_graph(self, size):

        to_run ='''int size = 2000;
            List ids = new ArrayList();
            Vertex v = graph.addVertex();
            v.property("ts", 100001);
            v.property("sin", 0);
            v.property("cos", 1);
            v.property("ii", 0);
            ids.add(v.id());
            Random rand = new Random();
            for (int ii = 1; ii < size; ii++) {
                v = graph.addVertex();
                v.property("ii", ii);
                v.property("ts", 100001 + ii);
                v.property("sin", Math.sin(ii/5.0));
                v.property("cos", Math.cos(ii/5.0));
                Vertex u = g.V(ids.get(rand.nextInt(ids.size()))).next();
                v.addEdge("linked", u);
                ids.add(u.id());
                ids.add(v.id());
            }
            g.V().count();'''
        self.session.execute_graph(to_run, timeout=32)
