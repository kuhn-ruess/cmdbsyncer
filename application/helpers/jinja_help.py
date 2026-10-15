"""
Jinja help for template fields

What the "Jinja help" panel next to a template field lists: the syncer's
own functions and filters, a few Jinja basics, the variables a rule hands
in and the existing lookup tables. Every entry has a snippet that a click
inserts into the field.

``tests/test_jinja_help.py`` checks that every function and filter
registered in ``syncer_jinja`` has an entry here, so a new one cannot be
added without its help.
"""
# pylint: disable=import-outside-toplevel
from application.docu_links import docu_links

# (name, snippet, description). The snippets are one line: the template
# fields are single line inputs. `attribute` stands for the name of a host
# attribute.
FUNCTIONS = (
    ('lookup',
     "{{ lookup('table', attribute, default='unknown') }}",
     "Value of a lookup table (Modules > Lookup Tables) for a key: the second "
     "column, or the column named as third argument."),
    ('get_list',
     "{% for item in get_list(attribute) %}{{ item }},{% endfor %}",
     "Turns a list, a list literal or a comma separated string into a list."),
    ('merge_list_of_dicts',
     "{{ merge_list_of_dicts(attribute)['key'] }}",
     "Merges a list of dicts into one dict, empty values are dropped."),
    ('eval',
     "{{ eval(attribute) }}",
     "Reads a string holding a Python literal (list, dict, number)."),
    ('defined',
     "{{ defined(attribute, 'fallback') }}",
     "The value, or the fallback when it is empty, 'false' or 'none'."),
    ('hash_value',
     "{{ hash_value(attribute) }}",
     "Short stable hash of a value, e.g. to make a label of a long list."),
    ('cmk_cleanup_tag_id',
     "{{ cmk_cleanup_tag_id(attribute) }}",
     "Cleans a value up to a valid Checkmk host tag id."),
    ('cmk_cleanup_hostname',
     "{{ cmk_cleanup_hostname(attribute) }}",
     "Cleans a value up to a valid Checkmk host name."),
    ('cmk_password',
     "{{ cmk_password('name') }}",
     "Password store reference of a Checkmk Password of the syncer."),
    ('get_ip_network',
     "{{ get_ip_network(attribute) }}",
     "Network of an address with mask: 10.1.2.3/255.255.255.0 gives "
     "10.1.2.0/255.255.255.0."),
    ('get_ip_interface',
     "{{ get_ip_interface(attribute) }}",
     "Address with prefix length: 10.1.2.3/255.255.255.0 gives 10.1.2.3/24."),
    ('get_ip4_interface',
     "{{ get_ip4_interface(attribute) }}",
     "Same as get_ip_interface."),
    ('datetime',
     "{{ datetime.datetime.now().strftime('%Y-%m-%d') }}",
     "The Python datetime module, e.g. for the current date."),
)

FILTERS = (
    ('hash',
     "{{ attribute | hash }}",
     "Filter form of hash_value."),
)

BASICS = (
    ('if / else',
     "{% if attribute == 'value' %}yes{% else %}no{% endif %}",
     "Different values depending on a condition."),
    ('default',
     "{{ attribute | default('unknown') }}",
     "Fallback for a host without the attribute (otherwise the whole value "
     "is empty)."),
    ('lower / upper',
     "{{ attribute | lower }}",
     "Lower case (upper for upper case)."),
    ('replace',
     "{{ attribute | replace('old', 'new') }}",
     "Replaces text in the value."),
    ('split',
     "{{ attribute.split('.')[0] }}",
     "Part of a value, e.g. the short name of an FQDN."),
    ('ACCOUNT',
     "{{ACCOUNT:account_name:field}}",
     "A field of an account, e.g. its address or password."),
)

# The variables the host based rules (Custom Attributes, Rewrite
# Attributes) hand in besides the host's attributes.
RULE_VARIABLES = (
    ('HOSTNAME', "{{ HOSTNAME }}", "Name of the host."),
    ('FIRST_MATCHING_TAG', "{{ FIRST_MATCHING_TAG }}",
     "Attribute name the first condition of the rule matched."),
    ('FIST_MATCHING_VALUE', "{{ FIST_MATCHING_VALUE }}",
     "Attribute value the first condition of the rule matched."),
    ('any attribute', "{{ attribute }}",
     "Every attribute of the host is a variable of its own name."),
)


def _entries(group, items):
    return [{'group': group, 'name': name, 'snippet': snippet, 'text': text}
            for name, snippet, text in items]


def lookup_tables():
    """
    Name and columns of every lookup table. Only the header line is
    parsed: a table can be long and the panel needs nothing else.
    """
    from application.models.lookup_table import LookupTable
    from application.modules.rule.list_source import parse_list_source
    tables = []
    for entry in LookupTable.objects.only('name', 'entries').order_by('name'):
        header = (entry.entries or '').strip('\r\n').split('\n', 1)[0]
        columns = parse_list_source(header).columns
        tables.append({'name': entry.name, 'key': columns[0] if columns else '',
                       'columns': columns[1:]})
    return tables


def jinja_help(fields, note=''):
    """
    What the help panel of a form needs: the fields (outcome field names)
    it is shown for, a note on when they are rendered, the entries and the
    lookup tables.
    """
    return {
        'fields': list(fields),
        'note': note,
        'entries': (_entries('Variables', RULE_VARIABLES)
                    + _entries('Syncer functions', FUNCTIONS)
                    + _entries('Syncer filters', FILTERS)
                    + _entries('Jinja basics', BASICS)),
        'tables': lookup_tables(),
        'docs': docu_links['jinja_functions'],
    }
