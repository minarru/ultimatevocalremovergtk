"""Toolchain formatting may differ; widget content must not."""

import unittest

from scripts.check_resource_bundle import normalize_xml


class ResourceComparisonTests(unittest.TestCase):
    def test_indentation_comments_and_attribute_order_do_not_change_content(self):
        first = b'<interface><!-- compiler --><object id="a" class="GtkLabel"><property name="label"> Hello </property></object></interface>'
        second = b'<interface>\n  <object class="GtkLabel" id="a">\n    <property name="label"> Hello </property>\n  </object>\n</interface>'
        self.assertEqual(normalize_xml(first), normalize_xml(second))

    def test_property_values_and_leaf_whitespace_remain_significant(self):
        first = b'<interface><property name="label"> </property></interface>'
        second = b'<interface><property name="label"></property></interface>'
        self.assertNotEqual(normalize_xml(first), normalize_xml(second))
        self.assertNotEqual(
            normalize_xml(first), normalize_xml(first.replace(b'label', b'tooltip-text'))
        )
