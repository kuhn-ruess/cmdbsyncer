"""
Checkmk Users Sync
"""
from application import logger
from application.plugins.checkmk.cmk2 import CMK2
from application.modules.rule.rule import Rule
from application.plugins.checkmk.models import CheckmkUserMngmt

from syncerapi.v1 import cc as CC


str_replace = Rule.replace

class CheckmkUserSync(CMK2):
    """
    Export Users to Checkmk
    """
    name = "Synce Users to Checkmk"
    source = "cmk_user_sync"

    def export_users(self):
        """
        Export Checkmk Users
        """
        checks = [
            'fullname', 'disable_login',
            'pager_address', 'contactgroups',
            'roles', 'contact_options.email',
        ]
        for user in CheckmkUserMngmt.objects(disabled__ne=True):
            url = f"/objects/user_config/{user.user_id}"
            cmk_user = self.request(url, method="GET")
            # ({}, {'status_code': 404})
            user_template = {
              "username": user.user_id,
              "fullname": user.full_name,
              "auth_option": {
                "auth_type": "password",
                "password": user.password
              },
              "disable_login": user.disable_login,
              "contact_options": {
                "email": user.email
              },
              "pager_address": user.pager_address,
              "idle_timeout": {
                "option": "global"
              },
              "roles": user.roles,
              #"authorized_sites": [
              #  "heute"
              #],
              "contactgroups": user.contact_groups,
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
                logger.debug(f"Response {response}")
            else:
                # We May Update the User (or delete him)
                if user.remove_if_found:
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Deleted")
                    self.request(url, method="DELETE")
                    continue

                etag = cmk_user[1]['ETag']
                cmk_data = cmk_user[0]['extensions']
                changed = False
                for check in checks:
                    if '.' in check:
                        first_level, second_level = check.split('.')
                        cmk_current = cmk_data.get(first_level,{}).get(second_level)
                        tmpl_current = user_template[first_level][second_level]
                    else:
                        cmk_current = cmk_data.get(check)
                        tmpl_current = user_template[check]
                    if cmk_current != tmpl_current:
                        changed = True
                        logger.debug(f"{check}: {tmpl_current} vs {cmk_current}")
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
