"""Small local checks for the read-only public verification boundary."""
import unittest
import urllib.request
from unittest.mock import patch

from tools import verify_published_launcher_update as verification


class VerificationGuardTests(unittest.TestCase):
    def test_package_pins_exact_manifest_without_arbitrary_url(self):
        value=verification.validate_package({'version':'0.1.5','sha256':'a'*64,'size':118737056})
        self.assertEqual(value,{'schema':1,'version':'0.1.5','sha256':'a'*64,'size':118737056})

    def test_reject_path_versions_bad_hash_and_unbounded_size(self):
        base={'version':'0.1.5','sha256':'a'*64,'size':118737056}
        for field,value in (('version','../x'),('version','0.1.5?x'),('sha256','A'*64),('size',True),('size',300*1024*1024)):
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                verification.validate_package({**base,field:value})

    def test_redirect_handler_refuses_origin_or_tls_change_before_following(self):
        request=urllib.request.Request('https://ti-reborn.com/downloads/a.exe')
        handler=verification.SameOriginRedirect()
        for destination in ('http://ti-reborn.com/a.exe','https://example.com/a.exe','https://ti-reborn.com:444/a.exe'):
            with self.subTest(destination=destination),self.assertRaises(ValueError):
                handler.redirect_request(request,None,302,'Found',{},destination)
        redirected=handler.redirect_request(request,None,302,'Found',{},'https://ti-reborn.com:443/downloads/b.exe')
        self.assertEqual(redirected.full_url,'https://ti-reborn.com:443/downloads/b.exe')

    def test_streaming_download_hashes_without_retaining_binary(self):
        class Response:
            status=200;url='https://ti-reborn.com/a.exe';headers={}
            def __init__(self):self.chunks=iter((b'first',b'second',b''))
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return next(self.chunks)
        with patch.object(verification.urllib.request,'build_opener') as builder:
            builder.return_value.open.return_value=Response()
            record,raw=verification.fetch(Response.url,binary=True)
        self.assertEqual(raw,b'')
        self.assertEqual(record['bytes'],11)
        self.assertEqual(record['sha256'],verification.hashlib.sha256(b'firstsecond').hexdigest())

    def test_remote_source_has_only_read_operations(self):
        source=verification.REMOTE_READ_ONLY
        compile(source,'readonly-verification','exec')
        self.assertIn('mode=ro',source)
        self.assertIn('PRAGMA integrity_check',source)
        for forbidden in ('UPDATE ','INSERT ','DELETE ','systemctl restart','write_text(','.backup('):
            self.assertNotIn(forbidden,source)


if __name__=='__main__':unittest.main()
