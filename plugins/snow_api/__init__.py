from syncerapi.v1.rest import API

from .rest_api.snow import API as snow_api
API.add_namespace(snow_api, path='/snow_api')
