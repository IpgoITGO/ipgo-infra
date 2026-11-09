import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[2]/'scripts/d0_publish_image.py'
spec=importlib.util.spec_from_file_location('d0_publish',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Missing(Exception):pass
class Client:
    class exceptions:ImageNotFoundException=Missing
    def __init__(self,error=None):self.error=error
    def describe_images(self,**kwargs):
        if self.error:raise self.error
        return {'imageDetails':[{}]}

class PublishTest(unittest.TestCase):
    def test_only_image_not_found_allows_new_tag(self):
        module.new_tag(Client(Missing()),'d0-'+'a'*40)
        for client in [Client(),Client(PermissionError('access denied')),Client(TimeoutError())]:
            with self.subTest(client=client),self.assertRaises(Exception):module.new_tag(client,'d0-'+'a'*40)
        with self.assertRaises(ValueError):module.new_tag(Client(Missing()),'latest')
