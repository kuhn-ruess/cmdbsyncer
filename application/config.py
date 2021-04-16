""" Config File """

class BaseConfig():
    """
    Generel System white Configuration.
    Can be overwritten later if needed.
    """
    SECRET_KEY = "j+}[56_c$%62ypu5F5PH)P4s~q(.H'mZH!dFkn?e!@{,f)Zj9Cd<Dj@DG"
    MONGODB_DB = "cmdb-api"


class ProductionConfig(BaseConfig):
    """
    Production Configuration.
    """
