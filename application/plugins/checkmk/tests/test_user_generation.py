"""
Unit tests for the Checkmk user generation
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
# pylint: disable=too-few-public-methods,too-many-instance-attributes
import re
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.helpers import foreach_attribute_items
from application.plugins.checkmk.user_generation import (
    CheckmkUserGeneration,
    group_search,
    read_ldap_groups,
    rewritten_group_name,
    render_entries,
    SelectedGroup,
)
from application.plugins.ldap.ldap import LdapSearchError


def fake_render(value, _ctx=None, **kwargs):
    """
    Minimal {{ var }} substitution standing in for the Jinja renderer,
    which the test bootstrap stubs out. Enough to prove which context a
    template is rendered against.
    """
    context = dict(_ctx if _ctx is not None else kwargs)
    return re.sub(r'\{\{\s*([^}\s]+)\s*\}\}',
                  lambda match: str(context.get(match.group(1), '')),
                  str(value or '')).strip()


class StoredUser:
    """Stand-in for a CheckmkUserMngmt document"""

    def __init__(self, **fields):
        self.user_id = ''
        self.full_name = ''
        self.email = ''
        self.pager_address = ''
        self.roles = []
        self.contact_groups = []
        self.disable_login = False
        self.generated_by_rule = None
        self.password = ''
        self.saved = 0
        for key, value in fields.items():
            setattr(self, key, value)

    def save(self):
        """Count the writes so a no-op run is visible"""
        self.saved += 1


def make_outcome(**overrides):
    """Outcome of a generation rule with usable defaults"""
    defaults = {
        'foreach_type': 'label',
        'foreach': 'ldap_group',
        'rewrite_group_name': '',
        'rewrite_user_id': '{{name}}',
        'rewrite_full_name': '{{name}}',
        'rewrite_email': '{{mail}}',
        'rewrite_pager_address': '',
        'ldap_account': '',
        'ldap_base_dn': '',
        'ldap_group_filter': '',
        'ldap_name_attribute': 'cn',
        'ldap_attributes': '',
        'roles': ['user'],
        'contact_groups': ['all'],
        'disable_login': True,
    }
    defaults.update(overrides)
    outcome = Mock()
    for key, value in defaults.items():
        setattr(outcome, key, value)
    return outcome


def selected(*names):
    """What group_names() hands the lookup: searched name plus its origin"""
    return [SelectedGroup(name=x, original=x) for x in names]


def make_rule(name='Rule', **overrides):
    """Generation rule carrying the given outcome"""
    rule = Mock()
    rule.name = name
    rule.outcome = make_outcome(**overrides)
    return rule


class TestForeachAttributeItems(unittest.TestCase):
    """The attribute selection both groups and users share"""

    index = (
        {
            'ldap_group': ['linux-admins', 'dba'],
            'ldap_group_second': ['windows-admins'],
            'multi': ['a,b'],
        },
        {
            'linux-admins': ['ldap_group'],
        },
    )

    def test_by_attribute_name(self):
        self.assertEqual(foreach_attribute_items(self.index, 'label', 'ldap_group'),
                         ['linux-admins', 'dba'])

    def test_by_attribute_value(self):
        self.assertEqual(foreach_attribute_items(self.index, 'value', 'linux-admins'),
                         ['ldap_group'])

    def test_wildcard_collects_every_matching_name(self):
        self.assertEqual(foreach_attribute_items(self.index, 'label', 'ldap_group*'),
                         ['linux-admins', 'dba', 'windows-admins'])

    @patch('application.plugins.checkmk.helpers.get_list',
           side_effect=lambda value: [x.strip() for x in str(value).split(',')])
    def test_list_splits_the_values(self, mock_get_list):
        self.assertEqual(foreach_attribute_items(self.index, 'list', 'multi'),
                         ['a', 'b'])

    def test_unknown_attribute_is_empty(self):
        self.assertEqual(foreach_attribute_items(self.index, 'label', 'nothing'), [])

    def test_missing_foreach_does_not_raise(self):
        self.assertEqual(foreach_attribute_items(self.index, 'label', None), [])

    def test_a_list_attribute_is_split(self):
        index = ({'ldap_group': ['dba, linux']}, {})
        with patch('application.plugins.checkmk.helpers.get_list',
                   side_effect=split_on_comma):
            self.assertEqual(foreach_attribute_items(index, 'list', 'ldap_group'),
                             ['dba', 'linux'])

    def test_a_list_attribute_with_a_wildcard_collects_every_match(self):
        # One attribute per team, each holding several groups, is the
        # same shape as one attribute holding all of them
        index = ({'ldap_group': ['dba, linux'],
                  'ldap_group_second': ['windows'],
                  'other': ['ignored']}, {})
        with patch('application.plugins.checkmk.helpers.get_list',
                   side_effect=split_on_comma):
            self.assertEqual(foreach_attribute_items(index, 'list', 'ldap_group*'),
                             ['dba', 'linux', 'windows'])


def split_on_comma(value):
    """
    Stands in for get_list, which the bootstrap stubs out with the rest
    of syncer_jinja. Enough to show which values reach it.
    """
    if isinstance(value, list):
        return value
    return [x.strip() for x in str(value).split(',') if x.strip()]


class TestRewrittenGroupName(unittest.TestCase):
    """A rewrite that cannot produce a name must not produce one"""

    def test_the_value_is_rendered_as_name_and_nullified(self):
        with patch('application.plugins.checkmk.user_generation.render_jinja',
                   return_value='grp-dba') as mock_render:
            self.assertEqual(rewritten_group_name('grp-{{name}}', 'dba'), 'grp-dba')

        self.assertEqual(mock_render.call_args[1]['_ctx']['name'], 'dba')
        # nullify: a variable the hosts do not carry empties the whole
        # template instead of leaving a half rendered name behind
        self.assertEqual(mock_render.call_args[1]['mode'], 'nullify')

    def test_a_template_blowing_up_on_the_value_is_an_empty_name(self):
        # e.g. {{name.split("@")[1]}} on a value without an @
        with patch('application.plugins.checkmk.user_generation.render_jinja',
                   side_effect=IndexError('list index out of range')):
            self.assertEqual(rewritten_group_name('{{name}}', 'dba'), '')

    def test_whitespace_only_is_an_empty_name(self):
        with patch('application.plugins.checkmk.user_generation.render_jinja',
                   return_value='   '):
            self.assertEqual(rewritten_group_name('{{name}}', 'dba'), '')


class TestRenderEntries(unittest.TestCase):
    """Roles and contact groups are Jinja too"""

    def setUp(self):
        patcher = patch('application.plugins.checkmk.user_generation.render_jinja',
                        side_effect=fake_render)
        patcher.start()
        self.addCleanup(patcher.stop)
        # get_list comes from the stubbed syncer_jinja
        patcher = patch('application.plugins.checkmk.user_generation.get_list',
                        side_effect=split_on_comma)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_plain_name_stays_what_it_is(self):
        self.assertEqual(render_entries(['all', 'linux'], {}),
                         ['all', 'linux'])

    def test_an_attribute_of_the_group_can_name_it(self):
        self.assertEqual(render_entries(['cg_{{name}}'], {'name': 'dba'}),
                         ['cg_dba'])

    def test_one_entry_can_produce_several(self):
        self.assertEqual(
            render_entries(['{{cmk_contactgroups}}'],
                           {'cmk_contactgroups': 'dba, linux'}),
            ['dba', 'linux'])

    def test_an_entry_rendering_to_nothing_is_dropped(self):
        self.assertEqual(render_entries(['all', '{{not_carried}}'], {}), ['all'])

    def test_the_same_name_is_only_taken_once(self):
        self.assertEqual(render_entries(['all', '{{name}}'], {'name': 'all'}),
                         ['all'])


class TestReadLdapGroups(unittest.TestCase):
    """The LDAP side of the generation"""

    @patch('application.plugins.checkmk.user_generation.get_group_attributes')
    @patch('application.plugins.checkmk.user_generation.get_account_by_name')
    def test_attributes_of_the_group_are_returned(self, mock_account, mock_lookup):
        mock_account.return_value = {'address': 'ldaps://srv', 'base_dn': 'dc=acc'}
        mock_lookup.return_value = {'dba': {'cn': 'dba', 'mail': 'dba@example.com'}}

        result = read_ldap_groups(group_search(make_outcome(ldap_account='ldap')),
                                  ['dba'])

        self.assertEqual(result, {'dba': {'cn': 'dba', 'mail': 'dba@example.com'}})

    @patch('application.plugins.checkmk.user_generation.get_group_attributes')
    @patch('application.plugins.checkmk.user_generation.get_account_by_name')
    def test_the_rule_decides_where_the_groups_are_searched(self, mock_account,
                                                            mock_lookup):
        # The account only knows the host import
        mock_account.return_value = {
            'address': 'ldaps://srv',
            'base_dn': 'dc=acc',
            'search_filter': '(objectClass=computer)',
        }
        mock_lookup.return_value = {}

        read_ldap_groups(group_search(make_outcome(
            ldap_account='ldap',
            ldap_base_dn='ou=groups,dc=acc',
            ldap_group_filter='(objectClass=group)',
            ldap_name_attribute='sAMAccountName',
            ldap_attributes='cn, mail, telephoneNumber')), ['dba'])

        config = mock_lookup.call_args[0][0]
        self.assertEqual(config['base_dn'], 'ou=groups,dc=acc')
        # The host filter of the account would never match a group
        self.assertEqual(config['search_filter'], '(objectClass=group)')
        self.assertEqual(mock_lookup.call_args[1]['name_attribute'], 'sAMAccountName')
        self.assertEqual(mock_lookup.call_args[1]['attributes'],
                         ['cn', 'mail', 'telephoneNumber'])

    @patch('application.plugins.checkmk.user_generation.get_group_attributes')
    @patch('application.plugins.checkmk.user_generation.get_account_by_name')
    def test_defaults_when_the_rule_configures_nothing(self, mock_account,
                                                       mock_lookup):
        mock_account.return_value = {'address': 'ldaps://srv', 'base_dn': 'dc=acc'}
        mock_lookup.return_value = {}

        read_ldap_groups(group_search(make_outcome(ldap_account='ldap')), ['dba'])

        self.assertEqual(mock_lookup.call_args[0][0]['base_dn'], 'dc=acc')
        self.assertEqual(mock_lookup.call_args[0][0]['search_filter'], '')
        self.assertEqual(mock_lookup.call_args[1]['name_attribute'], 'cn')
        # No list configured reads every attribute the group has
        self.assertEqual(mock_lookup.call_args[1]['attributes'], [])

    @patch('application.plugins.checkmk.user_generation.get_group_attributes')
    @patch('application.plugins.checkmk.user_generation.get_account_by_name')
    def test_a_given_filter_replaces_the_one_of_the_rule(self, mock_account,
                                                         mock_lookup):
        mock_account.return_value = {'address': 'ldaps://srv', 'base_dn': 'dc=acc'}
        mock_lookup.return_value = {}

        read_ldap_groups(group_search(
            make_outcome(ldap_account='ldap',
                         ldap_group_filter='(objectClass=group)'),
            '(objectClass=posixGroup)'), ['dba'])

        self.assertEqual(mock_lookup.call_args[0][0]['search_filter'],
                         '(objectClass=posixGroup)')

    @patch('application.plugins.checkmk.user_generation.get_group_attributes')
    @patch('application.plugins.checkmk.user_generation.get_account_by_name')
    def test_debug_reaches_the_lookup(self, mock_account, mock_lookup):
        mock_account.return_value = {'address': 'ldaps://srv', 'base_dn': 'dc=acc'}
        mock_lookup.return_value = {}

        read_ldap_groups(group_search(make_outcome(ldap_account='ldap')),
                         ['dba'], debug=True)

        self.assertTrue(mock_lookup.call_args[1]['debug'])

    @patch('application.plugins.checkmk.user_generation.get_account_by_name')
    def test_unknown_account_is_reported(self, mock_account):
        mock_account.return_value = False
        with self.assertRaises(LdapSearchError):
            read_ldap_groups(group_search(make_outcome(ldap_account='gone')), ['dba'])


class _SyncerTestCase(unittest.TestCase):
    """A CheckmkUserGeneration with the stubbed helpers wired up"""

    def setUp(self):
        self.syncer = CheckmkUserGeneration.__new__(CheckmkUserGeneration)
        self.syncer.log_details = []
        # The bootstrap stubs all three out; the rules only make sense
        # with a renderer that resolves the context and a get_list that
        # really splits.
        for target, replacement in (
                ('render_jinja', fake_render),
                ('get_list', split_on_comma),
                ('str_replace', lambda value, _exceptions=None: str(value))):
            patcher = patch(
                f'application.plugins.checkmk.user_generation.{target}',
                side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)


class TestGroupSelection(_SyncerTestCase):
    """Which groups a rule selects out of the host attributes"""

    def test_without_a_rewrite_the_attribute_value_is_the_group(self):
        index = ({'ldap_group': ['dba', 'linux']}, {})

        groups = self.syncer.group_names(make_rule(), index)

        self.assertEqual([x.name for x in groups], ['dba', 'linux'])
        # Nothing was rewritten, so both names are the same value
        self.assertEqual([x.original for x in groups], ['dba', 'linux'])

    def test_the_group_name_can_be_rewritten_before_it_is_searched(self):
        index = ({'ldap_group': ['dba', 'linux']}, {})

        groups = self.syncer.group_names(
            make_rule(rewrite_group_name='grp-{{name}}'), index)

        self.assertEqual([x.name for x in groups], ['grp-dba', 'grp-linux'])

    def test_the_value_behind_a_rewritten_name_is_kept(self):
        index = ({'ldap_group': ['dba']}, {})

        groups = self.syncer.group_names(
            make_rule(rewrite_group_name='grp-{{name}}'), index)

        self.assertEqual(groups[0].name, 'grp-dba')
        self.assertEqual(groups[0].original, 'dba')

    def test_a_value_rewriting_to_nothing_is_skipped(self):
        # Searching for an empty name would match whatever the group
        # filter alone matches, and create a user nobody asked for
        index = ({'ldap_group': ['dba', 'linux']}, {})

        groups = self.syncer.group_names(
            make_rule(rewrite_group_name='{{the_hosts_do_not_carry_this}}'), index)

        self.assertEqual(groups, [])

    def test_the_rewrite_cannot_produce_the_same_group_twice(self):
        index = ({'ldap_group': ['dba', 'linux']}, {})

        groups = self.syncer.group_names(
            make_rule(rewrite_group_name='one-team'), index)

        self.assertEqual([x.name for x in groups], ['one-team'])

    def test_every_group_is_collected_once(self):
        index = ({'ldap_group': ['dba', 'dba', 'linux']}, {})
        self.assertEqual(
            [x.name for x in self.syncer.group_names(make_rule(), index)],
            ['dba', 'linux'])


class TestCheckmkUserGeneration(_SyncerTestCase):
    """Creating and updating the generated users"""

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_creates_user_from_the_groups_attributes(self, mock_print, mock_model):
        mock_model.objects.return_value.first.return_value = None
        created = StoredUser()
        mock_model.return_value = created

        self.syncer.sync_user(make_rule(), 'dba', {'mail': 'dba@example.com'})

        self.assertEqual(created.full_name, 'dba')
        self.assertEqual(created.email, 'dba@example.com')
        self.assertEqual(created.generated_by_rule, 'Rule')
        self.assertEqual(created.roles, ['user'])
        self.assertTrue(created.disable_login)
        self.assertEqual(created.saved, 1)

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_any_group_attribute_can_be_used(self, mock_print, mock_model):
        mock_model.objects.return_value.first.return_value = None
        created = StoredUser()
        mock_model.return_value = created

        rule = make_rule(rewrite_full_name='{{description}}',
                         rewrite_pager_address='{{telephoneNumber}}')
        self.syncer.sync_user(rule, 'dba', {'mail': 'dba@example.com',
                                            'description': 'Database Team',
                                            'telephoneNumber': '+49123'})

        self.assertEqual(created.full_name, 'Database Team')
        self.assertEqual(created.pager_address, '+49123')

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_group_name_wins_over_an_attribute_called_name(self, mock_print,
                                                           mock_model):
        mock_model.objects.return_value.first.return_value = None
        created = StoredUser()
        mock_model.return_value = created

        self.syncer.sync_user(make_rule(), 'dba', {'name': 'something else'})

        self.assertEqual(mock_model.call_args[1]['user_id'], 'dba')

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_missing_attribute_leaves_the_field_alone(self, mock_print, mock_model):
        existing = StoredUser(user_id='dba', full_name='dba',
                              email='kept@example.com', roles=['user'],
                              contact_groups=['all'], disable_login=True,
                              generated_by_rule='Rule')
        mock_model.objects.return_value.first.return_value = existing

        # The group has no mail attribute at all
        self.syncer.sync_user(make_rule(), 'dba', {'cn': 'dba'})

        self.assertEqual(existing.email, 'kept@example.com')
        self.assertEqual(existing.saved, 0)

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_hand_made_user_is_not_touched(self, mock_print, mock_model):
        existing = StoredUser(user_id='dba', full_name='Someone')
        mock_model.objects.return_value.first.return_value = existing

        self.syncer.sync_user(make_rule(), 'dba', {'mail': 'dba@example.com'})

        self.assertEqual(existing.full_name, 'Someone')
        self.assertEqual(existing.saved, 0)

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_changed_mail_updates_the_user(self, mock_print, mock_model):
        existing = StoredUser(user_id='dba', full_name='dba', email='old@example.com',
                              roles=['user'], contact_groups=['all'],
                              disable_login=True, generated_by_rule='Rule')
        mock_model.objects.return_value.first.return_value = existing

        self.syncer.sync_user(make_rule(), 'dba', {'mail': 'new@example.com'})

        self.assertEqual(existing.email, 'new@example.com')
        self.assertEqual(existing.saved, 1)

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_unchanged_user_is_not_written(self, mock_print, mock_model):
        existing = StoredUser(user_id='dba', full_name='dba', email='dba@example.com',
                              roles=['user'], contact_groups=['all'],
                              disable_login=True, generated_by_rule='Rule')
        mock_model.objects.return_value.first.return_value = existing

        self.syncer.sync_user(make_rule(), 'dba', {'mail': 'dba@example.com'})

        self.assertEqual(existing.saved, 0)

    @patch('application.plugins.checkmk.user_generation.read_ldap_groups')
    @patch('builtins.print')
    def test_rules_with_the_same_search_share_one_query(self, mock_print,
                                                        mock_lookup):
        mock_lookup.return_value = {}
        same = {'ldap_account': 'ldap', 'ldap_group_filter': '(objectClass=group)'}
        self.syncer.lookup_groups([
            (make_rule('A', **same), selected('dba', 'linux')),
            (make_rule('B', **same), selected('linux', 'windows')),
            (make_rule('C'), selected('ignored')),
        ])

        # One search, carrying the groups of both rules
        mock_lookup.assert_called_once()
        self.assertEqual(mock_lookup.call_args[0][1], ['dba', 'linux', 'windows'])

    @patch('application.plugins.checkmk.user_generation.read_ldap_groups')
    @patch('builtins.print')
    def test_a_different_subtree_is_its_own_query(self, mock_print, mock_lookup):
        mock_lookup.return_value = {}
        self.syncer.lookup_groups([
            (make_rule('A', ldap_account='ldap', ldap_base_dn='ou=a'), selected('dba')),
            (make_rule('B', ldap_account='ldap', ldap_base_dn='ou=b'), selected('dba')),
        ])

        self.assertEqual(mock_lookup.call_count, 2)

    @patch('application.plugins.checkmk.user_generation.read_ldap_groups')
    @patch('builtins.print')
    def test_the_given_filter_beats_every_rule(self, mock_print, mock_lookup):
        mock_lookup.return_value = {}
        self.syncer.override_group_filter = '(objectClass=posixGroup)'
        self.syncer.lookup_groups([
            (make_rule('A', ldap_account='ldap',
                       ldap_group_filter='(objectClass=group)'), selected('dba')),
        ])

        self.assertEqual(mock_lookup.call_args[0][0].group_filter,
                         '(objectClass=posixGroup)')

    @patch('application.plugins.checkmk.user_generation.read_ldap_groups')
    @patch('builtins.print')
    def test_debug_names_the_groups_the_directory_does_not_have(self, mock_print,
                                                                mock_lookup):
        mock_lookup.return_value = {'dba': {'cn': 'dba'}}
        self.syncer.debug = True
        self.syncer.lookup_groups(
            [(make_rule('A', ldap_account='ldap'), selected('dba', 'linux'))])

        printed = ' '.join(str(call) for call in mock_print.call_args_list)
        self.assertIn('Not in the directory: linux', printed)

    @patch('application.plugins.checkmk.user_generation.read_ldap_groups')
    @patch('builtins.print')
    def test_failed_ldap_lookup_leaves_the_account_out(self, mock_print, mock_lookup):
        mock_lookup.side_effect = LdapSearchError("server down")

        found = self.syncer.lookup_groups(
            [(make_rule('A', ldap_account='ldap'), selected('dba'))])

        self.assertEqual(found, {})
        self.assertEqual(self.syncer.log_details[0][0], 'ERROR')

    @patch('application.plugins.checkmk.user_generation.CheckmkUserGenerationRule')
    @patch('application.plugins.checkmk.user_generation.collect_attribute_index')
    @patch('application.plugins.checkmk.user_generation.Host')
    @patch('builtins.print')
    def test_rule_of_a_failed_account_creates_no_user(self, mock_print, mock_host,
                                                      mock_index, mock_rules):
        mock_index.return_value = ({'ldap_group': ['dba']}, {})
        mock_rules.objects.return_value = [make_rule('A', ldap_account='ldap')]

        with patch.object(self.syncer, 'lookup_groups', return_value={}), \
                patch.object(self.syncer, 'sync_user') as mock_sync:
            self.syncer.generate_users()

        mock_sync.assert_not_called()

    def test_both_names_reach_the_user_templates(self):
        with patch.object(self.syncer, 'sync_user') as mock_sync, \
                patch.object(self.syncer, 'lookup_groups', return_value={}), \
                patch('application.plugins.checkmk.user_generation.Host'), \
                patch('application.plugins.checkmk.user_generation'
                      '.collect_attribute_index',
                      return_value=({'ldap_group': ['dba']}, {})), \
                patch('application.plugins.checkmk.user_generation'
                      '.CheckmkUserGenerationRule') as mock_rules, \
                patch('builtins.print'):
            mock_rules.objects.return_value = [
                make_rule('A', rewrite_group_name='grp-{{name}}')]
            self.syncer.generate_users()

        # The searched name and the value the host carried
        self.assertEqual(mock_sync.call_args[0][1], 'grp-dba')
        self.assertEqual(mock_sync.call_args[0][3], 'dba')

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_a_preview_plan_does_not_write(self, mock_print, mock_model):
        mock_model.objects.return_value.first.return_value = None

        plan = self.syncer.plan_user(make_rule(), 'dba', {'mail': 'dba@example.com'})

        self.assertEqual(plan['action'], 'create')
        self.assertEqual(plan['user_id'], 'dba')
        self.assertEqual(plan['fields']['contact_groups'], ['all'])
        mock_model.return_value.save.assert_not_called()

    @patch('application.plugins.checkmk.user_generation.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_a_hand_made_user_is_a_skipped_plan(self, mock_print, mock_model):
        mock_model.objects.return_value.first.return_value = StoredUser(
            user_id='dba', generated_by_rule=None)

        plan = self.syncer.plan_user(make_rule(), 'dba', {})

        self.assertEqual(plan['action'], 'skipped')
        self.assertIn('by hand', plan['note'])

    def test_the_user_context_carries_the_original_name(self):
        rendered = {}

        def remember(template, _ctx=None, **_kwargs):
            rendered.update(_ctx or {})
            return fake_render(template, _ctx=_ctx)

        with patch('application.plugins.checkmk.user_generation.render_jinja',
                   side_effect=remember), \
                patch('application.plugins.checkmk.user_generation'
                      '.CheckmkUserMngmt') as mock_model, \
                patch('builtins.print'):
            mock_model.objects.return_value.first.return_value = None
            self.syncer.sync_user(make_rule(), 'grp-dba', {'mail': 'x@y.z'}, 'dba')

        self.assertEqual(rendered['name'], 'grp-dba')
        self.assertEqual(rendered['original_name'], 'dba')
