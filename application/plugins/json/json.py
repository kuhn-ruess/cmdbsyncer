from application.plugins.rest.rest import RestImport

def import_hosts_json(account, debug=False):
    """
    Inner Function for Import JSON Data
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Import data from {account}"
    json_data.source = "json_file_import"
    data = json_data.get_from_file()
    json_data.import_hosts(data)