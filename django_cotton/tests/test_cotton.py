from django.test import TestCase

from django_cotton.tests.inline_test_case import CottonInlineTestCase
from django_cotton.tests.utils import get_compiled, get_rendered


class InlineTestCase(CottonInlineTestCase):
    def test_component_is_rendered(self):
        self.create_template(
            "cotton/component.html",
            """<div class="i-am-component">{{ slot }}</div>""",
        )

        self.create_template(
            "view.html",
            """<c-component>Hello, World!</c-component>""",
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")
            self.assertContains(response, '<div class="i-am-component">')
            self.assertContains(response, "Hello, World!")

    def test_new_lines_in_attributes_are_preserved(self):
        self.create_template(
            "cotton/preserved.html",
            """<div {{ attrs }}>{{ slot }}</div>""",
        )

        self.create_template(
            "preserved_view.html",
            """
            <c-preserved x-data="{
                attr1: 'im an attr',
                var1: 'im a var',
                method() {
                    return 'im a method';
                }
            }" />
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")

            self.assertTrue(
                """{
                attr1: 'im an attr',
                var1: 'im a var',
                method() {
                    return 'im a method';
                }
            }"""
                in response.content.decode()
            )

    def test_attributes_that_end_or_start_with_quotes_are_preserved(self):
        self.create_template(
            "cotton/preserve_quotes.html",
            """
        <div {{ attrs }}><div>
        """,
        )

        self.create_template(
            "preserve_quotes_view.html",
            """
            <c-preserve-quotes something="var ? 'this' : 'that'" />
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")

            self.assertContains(response, '''"var ? 'this' : 'that'"''')

    def test_we_can_govern_whole_attributes_in_html_elements(self):
        self.create_template(
            "cotton/attribute_govern.html",
            """
            <div {% if something %} class="first" {% else %} class="second" {% endif %}><div>
            """,
        )

        self.create_template(
            "attribute_govern_view.html",
            """
            <c-attribute-govern :something="False" />
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")
            self.assertContains(response, 'class="second"')
            self.assertNotContains(response, 'class="first"')

    def test_attribute_names_on_component_containing_hyphens_are_converted_to_underscores(
        self,
    ):
        self.create_template(
            "cotton/hyphens.html",
            """
            <div x-data="{{ x_data }}" x-init="{{ x_init }}"></div>
            """,
        )

        self.create_template(
            "hyphens_view.html",
            """
            <c-hyphens x-data="{}" x-init="do_something()" />
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")

            self.assertContains(response, 'x-data="{}" x-init="do_something()"')

    def test_attribute_names_on_cvars_containing_hyphens_are_converted_to_underscores(
        self,
    ):
        self.create_template(
            "cotton/cvar_hyphens.html",
            """
            <c-vars x-data="{}" x-init="do_something()" />
            
            <div x-data="{{ x_data }}" x-init="{{ x_init }}"></div>
            """,
        )

        self.create_template(
            "cvar_hyphens_view.html",
            """
            <c-cvar-hyphens />
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")

            self.assertContains(response, 'x-data="{}" x-init="do_something()"')

    def test_cotton_directory_can_be_configured(self):
        custom_dir = "components"

        self.create_template(
            f"{custom_dir}/component.html",
            """<div class="i-am-component">{{ slot }}</div>""",
        )

        self.create_template("view.html", """<c-component>Hello, World!</c-component>""", "view/")

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf(), COTTON_DIR=custom_dir):
            response = self.client.get("/view/")
            self.assertContains(response, '<div class="i-am-component">')
            self.assertContains(response, "Hello, World!")

    def test_equals_in_attribute_values(self):
        self.create_template(
            "cotton/equals.html",
            """
            <div {{ attrs }}><div>
            """,
        )

        self.create_template(
            "equals_view.html",
            """
            <c-equals
              @click="this=test"
            />
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")

            self.assertContains(response, '@click="this=test"')

    def test_spaces_are_maintained_around_expression_inside_attributes(self):
        self.create_template(
            "maintain_spaces_in_attributes_view.html",
            """
            <div some_attribute_{{ id }}_something="true"></div>
            """,
            "view/",
        )

        # Override URLconf
        with self.settings(ROOT_URLCONF=self.get_url_conf()):
            response = self.client.get("/view/")

            self.assertContains(response, "some_attribute__something")


class CottonTestCase(TestCase):
    def test_parent_component_is_rendered(self):
        response = self.client.get("/parent")
        self.assertContains(response, '<div class="i-am-parent">')

    def test_child_is_rendered(self):
        response = self.client.get("/child")
        self.assertContains(response, '<div class="i-am-parent">')
        self.assertContains(response, '<div class="i-am-child">')

    def test_self_closing_is_rendered(self):
        response = self.client.get("/self-closing")
        self.assertContains(response, '<div class="i-am-parent">')

    def test_named_slots_correctly_display_in_loop(self):
        response = self.client.get("/named-slot-in-loop")
        self.assertContains(response, "item name: Item 1")
        self.assertContains(response, "item name: Item 2")
        self.assertContains(response, "item name: Item 3")

    def test_attribute_passing(self):
        response = self.client.get("/attribute-passing")
        self.assertContains(
            response, '<div attribute_1="hello" and-another="woo1" thirdforluck="yes">'
        )

    def test_attribute_merging(self):
        response = self.client.get("/attribute-merging")
        self.assertContains(response, 'class="form-group another-class-with:colon extra-class"')

    def test_django_syntax_decoding(self):
        response = self.client.get("/django-syntax-decoding")
        self.assertContains(response, "some-class")

    def test_vars_are_converted_to_vars_frame_tags(self):
        compiled = get_compiled(
            """
            <c-vars var1="string with space" />
            
            content
        """
        )

        self.assertEquals(
            compiled,
            """{% cotton_vars_frame var1=var1|default:"string with space" %}content{% endcotton_vars_frame %}""",
        )

    def test_loader_preserves_duplicate_attributes(self):
        compiled = get_compiled("""<a href="#" class="test" class="test2">hello</a>""")

        self.assertEquals(
            compiled,
            """<a href="#" class="test" class="test2">hello</a>""",
        )

    def test_attrs_do_not_contain_vars(self):
        response = self.client.get("/vars-test")
        self.assertContains(response, "attr1: 'im an attr'")
        self.assertContains(response, "var1: 'im a var'")
        self.assertContains(response, """attrs: 'attr1="im an attr"'""")

    def test_strings_with_spaces_can_be_passed(self):
        response = self.client.get("/string-with-spaces")
        self.assertContains(response, "attr1: 'I have spaces'")
        self.assertContains(response, "var1: 'string with space'")
        self.assertContains(response, "default_var: 'default var'")
        self.assertContains(response, "named_slot: '")
        self.assertContains(response, "named_slot with spaces")
        self.assertContains(response, """attrs: 'attr1="I have spaces"'""")

    def test_named_slots_dont_bleed_into_sibling_components(self):
        html = """
            <c-test-component>
                component1 
                <c-slot name="named_slot">named slot 1</c-slot>
            </c-test-component>
            <c-test-component>
                component2 
            </c-test-component>
        """

        rendered = get_rendered(html)

        self.assertTrue("named_slot: 'named slot 1'" in rendered)
        self.assertTrue("named_slot: ''" in rendered)

    def test_template_variables_are_not_parsed(self):
        html = """
            <c-test-component attr1="variable" :attr2="variable">
                <c-slot name="named_slot">
                    <a href="#" silica:click.prevent="variable = 'lineage'">test</a>
                </c-slot>
            </c-test-component>
        """

        rendered = get_rendered(html, {"variable": 1})

        self.assertTrue("attr1: 'variable'" in rendered)
        self.assertTrue("attr2: '1'" in rendered)

    def test_valueless_attributes_are_process_as_true(self):
        response = self.client.get("/test/valueless-attributes")

        self.assertContains(response, "It's True")

    def test_component_attributes_can_converted_to_python_types(self):
        response = self.client.get("/test/eval-attributes")

        self.assertContains(response, "none is None")
        self.assertContains(response, "number is 1")
        self.assertContains(response, "boolean_true is True")
        self.assertContains(response, "boolean_false is False")
        self.assertContains(response, "list.0 is 1")
        self.assertContains(response, "dict.key is 'value'")
        self.assertContains(response, "listdict.0.key is 'value'")

    def test_cvars_can_be_converted_to_python_types(self):
        response = self.client.get("/test/eval-vars")

        self.assertContains(response, "none is None")
        self.assertContains(response, "number is 1")
        self.assertContains(response, "boolean_true is True")
        self.assertContains(response, "boolean_false is False")
        self.assertContains(response, "list.0 is 1")
        self.assertContains(response, "dict.key is 'value'")
        self.assertContains(response, "listdict.0.key is 'value'")

    def test_attributes_can_contain_django_native_tags(self):
        response = self.client.get("/test/native-tags-in-attributes")

        self.assertContains(response, "Attribute 1 says: 'Hello Will'")
        self.assertContains(response, "Attribute 2 says: 'world'")
        self.assertContains(response, "Attribute 3 says: 'cowabonga!'")

        self.assertContains(
            response,
            """attrs tag is: 'normal="normal" attr1="Hello Will" attr2="world" attr3="cowabonga!"'""",
        )

    def test_loader_scans_all_app_directories(self):
        response = self.client.get("/test/unspecified-app-directory-template")

        self.assertContains(
            response,
            """My template was not specified in settings!""",
        )

    def test_expression_tags_close_to_tag_elements_doesnt_corrupt_the_tag(self):
        html = """
            <div{% if 1 = 1 %} attr1="variable" {% endif %}></div>
        """

        rendered = get_compiled(html)

        self.assertFalse("</div{% if 1 = 1 %}>" in rendered, "Tag corrupted")
        self.assertTrue("</div>" in rendered, "</div> not found in rendered string")
