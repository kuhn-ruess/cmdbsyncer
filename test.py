#!/usr/bin/env python3
import requests

url = "http://192.168.1.252:5002/cmk/check_mk/api/1.0/objects/password/cmdbsyncer_668f9bc4795454621fd61b87"

payload = {'headers': {'Accept': 'application/json',
             'Authorization': 'Bearer cmkadmin Test123$',
             'Content-Type': 'application/json'},
 'json': {'comment': '',
          'owner': 'admin',
          'password': 'Test123$4',
          'shared': [],
          'title': 'test'},
 'timeout': 30,
 'verify': False}

requests.put(url, **payload)
