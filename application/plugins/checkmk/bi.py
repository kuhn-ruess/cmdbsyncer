"""
Checkmk BI Rules
"""
# pylint: disable=logging-fstring-interpolation,too-many-locals
# pylint: disable=too-many-branches,too-many-statements,no-member
import ast
from application import logger, log
from application.plugins.checkmk.cmk2 import CMK2
from application.modules.rule.rule import Rule

from syncerapi.v1 import render_jinja, cc as CC, Host

str_replace = Rule.replace

class BI(CMK2):
    """
    Sync jobs for Checkmk Config
    """



#   .-- Export Bi Rules
    def export_bi_rules(self):
        """
        Export BI Rules
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        unique_rules = {}
        related_packs = []
        for db_host in Host.objects(object_type__ne='template'):
            logger.debug(f"Working on {db_host.hostname}")
            attributes = self.get_attributes(db_host, 'checkmk')
            logger.debug(f"His Attributes {attributes}")
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            logger.debug(f"His Actions {host_actions}")
            if host_actions:
                for _rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value. Admin-editable templates can be
                        # malformed — skip and log so one broken rule cannot
                        # abort the whole export.
                        rule_body = \
                            render_jinja(rule_params['rule_template'], **attributes['all'])
                        try:
                            rule_dict = ast.literal_eval(rule_body.replace('null', 'None'))
                            rule_id = rule_dict['id']
                            pack_id = rule_dict['pack_id']
                        except (ValueError, SyntaxError, TypeError, KeyError) as exc:
                            logger.error(
                                f"Skipping BI rule for host {db_host.hostname}:"
                                f" malformed rule_template ({exc})"
                            )
                            log.log(
                                "Skipping malformed BI rule template",
                                details=[
                                    ('host', db_host.hostname),
                                    ('error', str(exc)),
                                ],
                                source="CMK BI",
                            )
                            print(
                                f"{CC.FAIL} *{CC.ENDC} Skipping BI rule for"
                                f" {db_host.hostname}: malformed rule_template"
                            )
                            continue
                        unique_rules[rule_id] = rule_dict
                        if pack_id not in related_packs:
                            related_packs.append(pack_id)
                            logger.debug(f"Rule for Checkmk {rule_dict}")


        print(f"{CC.OKGREEN} -- {CC.ENDC} Load Rule Packs from Checkmk")
        found_list = []
        create_list = []
        sync_list = []
        delete_list = []
        unique_rules_keys = list(unique_rules.keys())
        for pack in related_packs:
            print(f"{CC.HEADER}Check Pack {pack} {CC.ENDC}")
            url = f"/objects/bi_pack/{pack}"
            response = self.request(url, method="GET")
            for cmk_rule in response[0]['members']['rules']['value']:
                cmk_rule_id = cmk_rule['href'].split('/')[-1]
                found_list.append(cmk_rule_id)
                if cmk_rule_id not in unique_rules_keys:
                    delete_list.append(cmk_rule_id)
            for local_rule in unique_rules_keys:
                if local_rule not in found_list:
                    create_list.append(local_rule)
                else:
                    sync_list.append(local_rule)

            for delete_id in delete_list:
                url = f"/objects/bi_rule/{delete_id}"
                del_response = self.request(url, method="DELETE")[1]
                print(f"{CC.WARNING} *{CC.ENDC} Rule {delete_id} deleted. Status: {del_response}")

            for create_id in create_list:
                url = f"/objects/bi_rule/{create_id}"
                data = unique_rules[create_id]
                self.request(url, data=data, method="POST")
                print(f"{CC.OKGREEN} *{CC.ENDC} Rule {create_id} created.")

            for sync_id in sync_list:
                print(f"{CC.OKGREEN} *{CC.ENDC} Check {sync_id} for Changes.")
                url = f"/objects/bi_rule/{sync_id}"
                cmk_rule = self.request(url, method="GET")[0]
                if cmk_rule != unique_rules[sync_id]:
                    print(f"{CC.WARNING}   *{CC.ENDC} Sync needed")
                    data = unique_rules[sync_id]
                    self.request(url, data=data,  method="PUT")
#.
#   .-- Export BI Aggregations
    def export_bi_aggregations(self):
        """
        Export BI Aggregations
        """
        print(f"\n{CC.HEADER}Build needed Aggregations{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        unique_aggregations = {}
        related_packs = []
        for db_host in Host.objects(object_type__ne='template'):
            logger.debug(f"Working on {db_host.hostname}")
            attributes = self.get_attributes(db_host, 'checkmk')
            logger.debug(f"His Attributes {attributes}")
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            logger.debug(f"His Actions {host_actions}")
            if host_actions:
                for _rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value. Admin-editable templates can be
                        # malformed — skip and log so one broken rule cannot
                        # abort the whole export.
                        rule_body = \
                            render_jinja(rule_params['rule_template'], **attributes['all'])
                        try:
                            aggregation_dict = ast.literal_eval(
                                rule_body.replace('null', 'None'))
                            aggregation_id = aggregation_dict['id']
                            pack_id = aggregation_dict['pack_id']
                        except (ValueError, SyntaxError, TypeError, KeyError) as exc:
                            logger.error(
                                f"Skipping BI aggregation for host"
                                f" {db_host.hostname}: malformed"
                                f" rule_template ({exc})"
                            )
                            log.log(
                                "Skipping malformed BI aggregation template",
                                details=[
                                    ('host', db_host.hostname),
                                    ('error', str(exc)),
                                ],
                                source="CMK BI",
                            )
                            print(
                                f"{CC.FAIL} *{CC.ENDC} Skipping BI aggregation"
                                f" for {db_host.hostname}: malformed rule_template"
                            )
                            continue
                        unique_aggregations[aggregation_id] = aggregation_dict
                        if pack_id not in related_packs:
                            related_packs.append(pack_id)
                            logger.debug(
                                f"Aggregation for Checkmk {aggregation_dict}")


        print(f"{CC.OKGREEN} -- {CC.ENDC} Load Rule Packs from Checkmk")
        found_list = []
        create_list = []
        sync_list = []
        delete_list = []
        unique_aggregation_keys = list(unique_aggregations.keys())
        for pack in related_packs:
            print(f"{CC.HEADER}Check Pack {pack} {CC.ENDC}")
            url = f"/objects/bi_pack/{pack}"
            response = self.request(url, method="GET")
            for cmk_rule in response[0]['members']['aggregations']['value']:
                cmk_rule_id = cmk_rule['href'].split('/')[-1]
                found_list.append(cmk_rule_id)
                if cmk_rule_id not in unique_aggregation_keys:
                    delete_list.append(cmk_rule_id)
            for local_rule in unique_aggregation_keys:
                if local_rule not in found_list:
                    create_list.append(local_rule)
                else:
                    sync_list.append(local_rule)

            for delete_id in delete_list:
                url = f"/objects/bi_aggregation/{delete_id}"
                del_response = self.request(url, method="DELETE")[1]
                print(f"{CC.WARNING} *{CC.ENDC} Aggr. {delete_id} deleted. Resp: {del_response}")

            for create_id in create_list:
                url = f"/objects/bi_aggregation/{create_id}"
                data = unique_aggregations[create_id]
                self.request(url, data=data, method="POST")
                print(f"{CC.OKGREEN} *{CC.ENDC} Aggregation {create_id} created.")

            for sync_id in sync_list:
                print(f"{CC.OKGREEN} *{CC.ENDC} Check Aggregation {sync_id} for Changes.")
                url = f"/objects/bi_aggregation/{sync_id}"
                cmk_rule = self.request(url, method="GET")[0]
                if cmk_rule != unique_aggregations[sync_id]:
                    print(f"{CC.WARNING}   *{CC.ENDC} Sync needed")
                    data = unique_aggregations[sync_id]
                    self.request(url, data=data,  method="PUT")

#.
#   . Export Checkmk User
#.
