"""
Checkmk Users Sync
"""
from application import logger
from application.plugins.checkmk.cmk2 import CMK2
from application.modules.rule.rule import Rule
from application.plugins.checkmk.user_models import CheckmkUserMngmt

from syncerapi.v1 import cc as CC


str_replace = Rule.replace

class CheckmkUserSync(CMK2):
    """
    Export Users to Checkmk
    """
    name = "Synce Users to Checkmk"
    source = "cmk_user_sync"

    @staticmethod
    def has_changes(cmk_data, user_template):
        """
        True when Checkmk's version of the user differs from what the
        Syncer would send. Only the fields the Syncer manages are
        compared, dotted names reach into the nested blocks.
        """
        checks = [
            'fullname', 'disable_login',
            'pager_address', 'contactgroups',
            'roles', 'contact_options.email',
        ]
        changed = False
        for check in checks:
            if '.' in check:
                first_level, second_level = check.split('.')
                cmk_current = cmk_data.get(first_level, {}).get(second_level)
                tmpl_current = user_template[first_level][second_level]
            else:
                cmk_current = cmk_data.get(check)
                tmpl_current = user_template[check]
            if cmk_current != tmpl_current:
                changed = True
                logger.debug("%s: %s vs %s", check, tmpl_current, cmk_current)
        return changed

    def export_users(self):
        """
        Export Checkmk Users
        """
        for user in CheckmkUserMngmt.objects(disabled__ne=True):
            url = f"/objects/user_config/{user.user_id}"
            cmk_user = self.request(url, method="GET")
            # ({}, {'status_code': 404})
            # A field never filled in is None on the document, and the
            # Checkmk API rejects null for every one of these ("pager
            # address may not be null"). Checkmk itself answers with the
            # empty value, so sending that is also what keeps has_changes
            # from reporting a difference on every single run.
            user_template = {
              "username": user.user_id,
              "fullname": user.full_name or user.user_id,
              "auth_option": {
                "auth_type": "password",
                "password": user.password
              },
              "disable_login": bool(user.disable_login),
              "contact_options": {
                "email": user.email or ''
              },
              "pager_address": user.pager_address or '',
              "idle_timeout": {
                "option": "global"
              },
              "roles": list(user.roles or []),
              #"authorized_sites": [
              #  "heute"
              #],
              "contactgroups": list(user.contact_groups or []),
              "disable_notifications": {
                "disable": False
              },
              "language": "en",
              "temperature_unit": "celsius",
              "interface_options": {
                "interface_theme": "dark"
              },
            }
            if not cmk_user[0]:
                if user.remove_if_found:
                    continue
                # We need to create the user
                print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Created")
                url = "/domain-types/user_config/collections/all"
                response = self.request(url, data=user_template, method="POST")
                logger.debug("Response %s", response)
            else:
                # We May Update the User (or delete him)
                if user.remove_if_found:
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Deleted")
                    self.request(url, method="DELETE")
                    continue

                etag = cmk_user[1]['ETag']
                changed = self.has_changes(cmk_user[0]['extensions'], user_template)
                if changed or user.overwrite_password:
                    if not user.overwrite_password:
                        del user_template['auth_option']
                    del user_template['username']
                    update_headers = {
                        'if-match': etag
                    }
                    update_url = f"/objects/user_config/{user.user_id}"
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Updated")
                    self.request(update_url, method="PUT",
                        data=user_template,
                        additional_header=update_headers)
                else:
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Nothing to do")
