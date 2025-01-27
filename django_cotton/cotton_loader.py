import warnings
import hashlib
import random
import os
import re

from django.template.loaders.base import Loader as BaseLoader
from django.core.exceptions import SuspiciousFileOperation
from django.template import TemplateDoesNotExist
from bs4.formatter import HTMLFormatter
from django.utils._os import safe_join
from django.template import Template
from django.core.cache import cache
from django.template import Origin
from django.conf import settings
from django.apps import apps

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# If an update changes the API that a cached version of a template will break, we increment the cache version in order to
# force the re-rendering of the template
cache_version = "2"


class Loader(BaseLoader):
    is_usable = True

    def __init__(self, engine, dirs=None):
        super().__init__(engine)
        self.cache_handler = CottonTemplateCacheHandler()
        self.cotton_compiler = CottonCompiler()
        self.dirs = dirs

    def get_contents(self, origin):
        # check if file exists, whilst getting the mtime for cache key
        try:
            mtime = os.path.getmtime(origin.name)
        except FileNotFoundError:
            raise TemplateDoesNotExist(origin)

        cache_key = self.cache_handler.get_cache_key(origin.template_name, mtime)
        cached_content = self.cache_handler.get_cached_template(cache_key)

        if cached_content is not None:
            return cached_content

        template_string = self._get_template_string(origin.name)

        # Do we need to process the template?
        if "<c-" not in template_string and "{% cotton_verbatim" not in template_string:
            raise TemplateDoesNotExist(origin)

        compiled_template = self.cotton_compiler.process(template_string, origin.template_name)

        self.cache_handler.cache_template(cache_key, compiled_template)

        return compiled_template

    def get_template_from_string(self, template_string):
        """Create and return a Template object from a string. Used primarily for testing."""
        return Template(template_string, engine=self.engine)

    def _get_template_string(self, template_name):
        try:
            with open(template_name, "r", encoding=self.engine.file_charset) as f:
                return f.read()
        except FileNotFoundError:
            raise TemplateDoesNotExist(template_name)

    def get_dirs(self):
        """This works like the file loader with APP_DIRS = True."""
        dirs = self.dirs if self.dirs is not None else self.engine.dirs

        for app_config in apps.get_app_configs():
            template_dir = os.path.join(app_config.path, "templates")
            if os.path.isdir(template_dir):
                dirs.append(template_dir)

        return dirs

    def get_template_sources(self, template_name):
        """Return an Origin object pointing to an absolute path in each directory
        in template_dirs. For security reasons, if a path doesn't lie inside
        one of the template_dirs it is excluded from the result set."""
        for template_dir in self.get_dirs():
            try:
                name = safe_join(template_dir, template_name)
            except SuspiciousFileOperation:
                # The joined path was located outside of this template_dir
                # (it might be inside another one, so this isn't fatal).
                continue

            yield Origin(
                name=name,
                template_name=template_name,
                loader=self,
            )


class UnsortedAttributes(HTMLFormatter):
    """This keeps BS4 from re-ordering attributes"""

    def attributes(self, tag):
        for k, v in tag.attrs.items():
            yield k, v


class CottonCompiler:
    DJANGO_SYNTAX_PLACEHOLDER_PREFIX = "__django_syntax__"
    COTTON_VERBATIM_PATTERN = re.compile(
        r"\{% cotton_verbatim %\}(.*?)\{% endcotton_verbatim %\}", re.DOTALL
    )
    DJANGO_TAG_PATTERN = re.compile(r"(\s?)(\{%.*?%\})(\s?)")
    DJANGO_VAR_PATTERN = re.compile(r"(\s?)(\{\{.*?\}\})(\s?)")

    def __init__(self):
        self.django_syntax_placeholders = []

    def process(self, content, template_name):
        content = self._replace_syntax_with_placeholders(content)
        content = self._compile_cotton_to_django(content, template_name)
        content = self._fix_bs4_attribute_empty_attribute_behaviour(content)
        content = self._replace_placeholders_with_syntax(content)
        content = self._remove_duplicate_attribute_markers(content)

        return content

    def _replace_syntax_with_placeholders(self, content):
        """Replace {% ... %} and {{ ... }} with placeholders so they dont get touched
        or encoded by bs4. We will replace them back after bs4 has done its job."""
        self.django_syntax_placeholders = []

        def replace_pattern(pattern, replacement_func):
            return pattern.sub(replacement_func, content)

        def replace_cotton_verbatim(match):
            """{% cotton_verbatim %} protects the content through the bs4 parsing process when we want to actually print
            cotton syntax in <pre> blocks."""
            inner_content = match.group(1)
            self.django_syntax_placeholders.append({"type": "verbatim", "content": inner_content})
            return (
                f"{self.DJANGO_SYNTAX_PLACEHOLDER_PREFIX}{len(self.django_syntax_placeholders)}__"
            )

        def replace_django_syntax(match):
            """Store if the match had at least one space on the left or right side of the syntax so we can restore it later"""
            left_space, syntax, right_space = match.groups()
            self.django_syntax_placeholders.append(
                {
                    "type": "django",
                    "content": syntax,
                    "left_space": bool(left_space),
                    "right_space": bool(right_space),
                }
            )
            return (
                f" {self.DJANGO_SYNTAX_PLACEHOLDER_PREFIX}{len(self.django_syntax_placeholders)}__ "
            )

        # Replace cotton_verbatim blocks
        content = replace_pattern(self.COTTON_VERBATIM_PATTERN, replace_cotton_verbatim)

        # Replace {% ... %}
        content = replace_pattern(self.DJANGO_TAG_PATTERN, replace_django_syntax)

        # Replace {{ ... }}
        content = replace_pattern(self.DJANGO_VAR_PATTERN, replace_django_syntax)

        return content

    def _compile_cotton_to_django(self, html_content, template_name):
        """Convert cotton <c-* syntax to {%."""
        soup = BeautifulSoup(
            html_content,
            "html.parser",
            on_duplicate_attribute=self.handle_duplicate_attributes,
        )

        # check if soup contains a 'c-vars' tag
        if cvars_el := soup.find("c-vars"):
            soup = self._wrap_with_cotton_vars_frame(soup, cvars_el)

        self._transform_components(soup, template_name)

        return str(soup.encode(formatter=UnsortedAttributes()).decode("utf-8"))

    def _replace_placeholders_with_syntax(self, content):
        """Replace placeholders with original syntax."""
        for i, placeholder in enumerate(self.django_syntax_placeholders, 1):
            if placeholder["type"] == "verbatim":
                placeholder_pattern = f"{self.DJANGO_SYNTAX_PLACEHOLDER_PREFIX}{i}__"
                content = content.replace(placeholder_pattern, placeholder["content"])
            else:
                """
                Construct the regex pattern based on original whitespace. This is to avoid unnecessary whitespace
                changes in the output that can lead to unintended tag type mutations,
                i.e. <div{% expr %}></div> --> <div__placeholder></div__placeholder> --> <div{% expr %}></div{% expr %}>
                """
                left_group = r"(\s*)" if not placeholder["left_space"] else ""
                right_group = r"(\s*)" if not placeholder["right_space"] else ""
                placeholder_pattern = (
                    f"{left_group}{self.DJANGO_SYNTAX_PLACEHOLDER_PREFIX}{i}__{right_group}"
                )

                content = re.sub(placeholder_pattern, placeholder["content"], content)

        return content

    def _remove_duplicate_attribute_markers(self, content):
        return re.sub(r"__COTTON_DUPE_ATTR__[0-9A-F]{5}", "", content, flags=re.IGNORECASE)

    def _fix_bs4_attribute_empty_attribute_behaviour(self, contents):
        """Bs4 adds ="" to valueless attribute-like parts in HTML tags that causes issues when we want to manipulate
        django expressions."""
        contents = contents.replace('=""', "")

        return contents

    def _wrap_with_cotton_vars_frame(self, soup, cvars_el):
        """If the user has defined a <c-vars> tag, wrap content with {% cotton_vars_frame %} to be able to create and
        govern vars and attributes. To be able to defined new vars within a component and also have them available in the
        same component's context, we wrap the entire contents in another component: cotton_vars_frame. Only when <c-vars>
        is present."""

        vars_with_defaults = []
        for var, value in cvars_el.attrs.items():
            # Attributes in context at this point will already have been formatted in _component to be accessible, so in order to cascade match the style.
            accessible_var = var.replace("-", "_")

            if value is None:
                vars_with_defaults.append(f"{var}={accessible_var}")
            elif var.startswith(":"):
                # If ':' is present, the user wants to parse a literal string as the default value,
                # i.e. "['a', 'b']", "{'a': 'b'}", "True", "False", "None" or "1".
                var = var[1:]  # Remove the ':' prefix
                accessible_var = accessible_var[1:]  # Remove the ':' prefix
                vars_with_defaults.append(f'{var}={accessible_var}|eval_default:"{value}"')
            else:
                # Assuming value is already a string that represents the default value
                vars_with_defaults.append(f'{var}={accessible_var}|default:"{value}"')

        cvars_el.decompose()

        # Construct the {% with %} opening tag
        opening = "{% cotton_vars_frame " + " ".join(vars_with_defaults) + " %}"
        closing = "{% endcotton_vars_frame %}"

        # Convert the remaining soup back to a string and wrap it within {% with %} block
        wrapped_content = (
            opening
            + str(soup.encode(formatter=UnsortedAttributes()).decode("utf-8")).strip()
            + closing
        )

        # Since we can't replace the soup object itself, we create new soup instead
        new_soup = BeautifulSoup(
            wrapped_content,
            "html.parser",
            on_duplicate_attribute=self.handle_duplicate_attributes,
        )

        return new_soup

    def _transform_components(self, soup, parent_key):
        """Replace <c-[component path]> tags with the {% cotton_component %} template tag"""
        for tag in soup.find_all(re.compile("^c-"), recursive=True):
            if tag.name == "c-slot":
                self._transform_named_slot(tag, parent_key)

                continue

            component_key = tag.name[2:]
            component_path = component_key.replace(".", "/").replace("-", "_")
            opening_tag = f"{{% cotton_component {'{}/{}.html'.format(settings.COTTON_DIR if hasattr(settings, 'COTTON_DIR') else 'cotton', component_path)} {component_key} "

            # Store attributes that contain template expressions, they are when we use '{{' or '{%' in the value of an attribute
            expression_attrs = []

            # Build the attributes
            for key, value in tag.attrs.items():
                # BS4 stores class values as a list, so we need to join them back into a string
                if key == "class":
                    value = " ".join(value)

                # Django templates tags cannot have {{ or {% expressions in their attribute values
                # Neither can they have new lines, let's treat them both as "expression attrs"
                if self.DJANGO_SYNTAX_PLACEHOLDER_PREFIX in value or "\n" in value or "=" in value:
                    expression_attrs.append((key, value))
                    continue

                opening_tag += ' {}="{}"'.format(key, value)
            opening_tag += " %}"

            component_tag = opening_tag

            if expression_attrs:
                for key, value in expression_attrs:
                    component_tag += f"{{% cotton_slot {key} {component_key} expression_attr %}}{value}{{% end_cotton_slot %}}"

            if tag.contents:
                tag_soup = BeautifulSoup(
                    tag.decode_contents(),
                    "html.parser",
                    on_duplicate_attribute=self.handle_duplicate_attributes,
                )
                self._transform_components(tag_soup, component_key)
                component_tag += str(
                    tag_soup.encode(formatter=UnsortedAttributes()).decode("utf-8")
                )

            component_tag += "{% end_cotton_component %}"

            # Replace the original tag with the compiled django syntax
            new_soup = BeautifulSoup(
                component_tag,
                "html.parser",
                on_duplicate_attribute=self.handle_duplicate_attributes,
            )
            tag.replace_with(new_soup)

        return soup

    def _transform_named_slot(self, slot_tag, component_key):
        """Compile <c-slot> to {% cotton_slot %}"""
        slot_name = slot_tag.get("name", "").strip()
        inner_html = "".join(str(content) for content in slot_tag.contents)

        # Check and process any components in the slot content
        slot_soup = BeautifulSoup(
            inner_html,
            "html.parser",
            on_duplicate_attribute=self.handle_duplicate_attributes,
        )
        self._transform_components(slot_soup, component_key)

        cotton_slot_tag = f"{{% cotton_slot {slot_name} {component_key} %}}{str(slot_soup.encode(formatter=UnsortedAttributes()).decode('utf-8'))}{{% end_cotton_slot %}}"

        slot_tag.replace_with(
            BeautifulSoup(
                cotton_slot_tag,
                "html.parser",
                on_duplicate_attribute=self.handle_duplicate_attributes,
            )
        )

    @staticmethod
    def handle_duplicate_attributes(tag_attrs, key, value):
        """BS4 cleans html and removes duplicate attributes. This would be fine if our target was html, but actually
        we're targeting Django Template Language. This contains expressions to govern content including attributes of
        any XML-like tag. It's perfectly fine to expect duplicate attributes per tag in DTL:

        <a href="#" {% if something %} class="this" {% else %} class="that" {% endif %}>Hello</a>

        The solution here is to make duplicate attribute keys unique across that tag so BS4 will not attempt to merge or
        replace existing. Then in post processing we'll remove the unique mask.
        """
        key_id = "".join(random.choice("0123456789ABCDEF") for i in range(5))
        key = f"{key}__COTTON_DUPE_ATTR__{key_id}"
        tag_attrs[key] = value


class CottonTemplateCacheHandler:
    """Handles caching of cotton templates so the html parsing is only done on first load of each view or component."""

    def __init__(self):
        self.enabled = getattr(settings, "COTTON_TEMPLATE_CACHING_ENABLED", True)

    def get_cache_key(self, template_name, mtime):
        template_hash = hashlib.sha256(template_name.encode()).hexdigest()
        return f"cotton_cache_v{cache_version}_{template_hash}_{mtime}"

    def get_cached_template(self, cache_key):
        if not self.enabled:
            return None

        return cache.get(cache_key)

    def cache_template(self, cache_key, content, timeout=None):
        if self.enabled:
            cache.set(cache_key, content, timeout=timeout)
