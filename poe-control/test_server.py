# SPDX-License-Identifier: Apache-2.0
import http.client
import json
import threading
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from server import (Controller, ControllerError, App, Server, validate_action,
                    validate_reply, PORT_MAP, Settings, port_config, requested_config, detection)


def frame(data):
    return bytes(data)+sum(data).to_bytes(2,'big')


def output(sent, received):
    return 'send msg: '+ ' '.join('0x%02x'%b for b in sent)+'\nread back: '+ ' '.join('0x%02x'%b for b in received)


class ProtocolTests(unittest.TestCase):
    def test_captured_live_reply_and_corruption(self):
        request=[2,0x80,5,0xc0,4,*([0x4e]*8)]
        sent=bytes.fromhex('02 69 05 c0 04 4e 4e 4e 4e 4e 4e 4e 4e 03 a4')
        reply=bytes.fromhex('03 69 1a 00 12 01 00 03 4e 4e 4e 01 41 01 c8')
        self.assertEqual(validate_reply(output(sent,reply),request),reply)
        for damaged in (reply[:-1], reply[:-1]+b'\x00',frame([3,0x70,*reply[2:13]])):
            with self.assertRaises(ControllerError):
                validate_reply(output(sent,damaged),request)

    def test_write_ack_and_rejection(self):
        request=[0,0x80,5,0xc0,2,0x0f,0xff,0xff,0,3,0x4e,0x4e,0x4e]
        sent=frame(request)
        ack=frame([0x52,0x80,0,0,*([0x4e]*9)])
        self.assertEqual(validate_reply(output(sent,ack),request),ack)
        rejected=frame([0x52,0x80,1,0,*([0x4e]*9)])
        with self.assertRaises(ControllerError):validate_reply(output(sent,rejected),request)

    def test_request_boundaries(self):
        for port in [0,13,True,1.0,'1; reboot',None]:
            with self.assertRaises(ValueError):validate_action({'port':port,'action':'power','value':'on'})
        for body in [{},[],{'port':1,'action':'init','value':True},
                     {'port':1,'action':'limit','value':90},
                     {'port':1,'action':'power','value':'on','shell':'reboot'}]:
            with self.assertRaises(ValueError):validate_action(body)
        self.assertEqual(validate_action({'port':12,'action':'power','value':'off'}),(12,'power','off'))
        self.assertEqual(PORT_MAP,(4,5,6,7,8,9,10,11,0,1,2,3))

    def test_delivery_pairs_and_disabled_configuration(self):
        c=Controller('/unused')
        # Protocol fixture: configured legacy mode and active power delivery.
        status=bytearray.fromhex('03 69 83 01 12 11 00 03 4e 4e 4e 01 41 00 00')
        measurement=bytes(15)
        c.query=lambda port,kind: bytes(status) if kind==0xc0 else measurement
        p=c.read_port(4)
        self.assertEqual(p['pairs'],2)
        self.assertEqual(p['detection'],'Legacy / non-IEEE')
        self.assertTrue(p['legacy'])
        status[2]=0x85
        self.assertEqual(c.read_port(4)['pairs'],2)
        status[2]=0x86
        self.assertEqual(c.read_port(4)['pairs'],4)
        status[2]=0x1a;status[3]=0
        p=c.read_port(4)
        self.assertFalse(p['enabled']);self.assertIsNone(p['pairs'])
        self.assertEqual(p['profile'],'60 W / 30 W')
        self.assertTrue(p['legacy'])

    def test_configure_only_changed_fields_and_noop(self):
        c=Controller('/unused');c.transact=Mock()
        before=config();wanted=dict(before,mode=0x12)
        c.read_port=Mock(return_value=wanted)
        c.configure(12,wanted,before=before)
        self.assertEqual(c.transact.call_args.args[0],[0,0x80,5,0xc0,3,0x0f,0xff,0x12,0,0xff,0x4e,0x4e,0x4e])
        c.transact.reset_mock()
        c.configure(12,wanted,before=wanted)
        c.transact.assert_not_called()

    def test_readback_failure_and_force_rejected(self):
        c=Controller('/unused');c.transact=Mock();c.read_port=Mock(return_value=config())
        with self.assertRaises(ControllerError):c.configure(1,dict(config(),enabled=True),before=config())
        c.transact.reset_mock()
        with self.assertRaises(ControllerError):c.configure(1,dict(config(),enabled=None))
        c.transact.assert_not_called()


def config():
    return {'enabled':False,'mode':1,'priority':'Low','cfg2':0x12,'extra_power':0}


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ports.json'
        self.c=Mock()
        self.c.read_port.side_effect=lambda p:dict(config(),port=p)

    def test_first_adoption_and_noop_restart(self):
        settings=Settings(self.path)
        self.assertEqual(settings.initialize(self.c),0)
        self.c.configure.assert_not_called()
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        Settings(self.path).initialize(self.c)
        self.c.configure.assert_not_called()

    def test_restore_enabled_empty_port_and_legacy_after_controller_reset(self):
        settings=Settings(self.path);settings.initialize(self.c)
        desired=dict(settings.ports)
        desired['4']=dict(config(),enabled=True,mode=0x11)
        desired['6']=dict(config(),enabled=True)
        settings.save(desired)
        self.assertEqual(Settings(self.path).initialize(self.c),2)
        self.assertEqual([call.args[0] for call in self.c.configure.call_args_list],[4,6])
        self.assertEqual(self.c.configure.call_args_list[0].args[1]['mode'],0x11)

    def test_bad_file_or_incomplete_scan_never_writes_hardware(self):
        self.path.write_text('{bad')
        with self.assertRaises(ControllerError):Settings(self.path)
        self.c.configure.assert_not_called()
        self.path.unlink()
        self.c.read_port.side_effect=[dict(config(),port=1),ControllerError('UART timeout')]
        with self.assertRaises(ControllerError):Settings(self.path).initialize(self.c)
        self.assertFalse(self.path.exists());self.c.configure.assert_not_called()

    def test_save_failure_prevents_hardware_change(self):
        settings=Settings(self.path);settings.initialize(self.c)
        app=App(self.c,settings)
        with patch('server.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(ControllerError):app.change(4,'legacy',True)
        self.c.configure.assert_not_called()
        self.assertEqual(Settings(self.path).ports['4']['mode'],1)

    def test_failed_ack_keeps_intent_for_next_start(self):
        settings=Settings(self.path);settings.initialize(self.c)
        self.c.configure.side_effect=ControllerError('timeout')
        app=App(self.c,settings)
        with self.assertRaisesRegex(ControllerError,'Settings saved'):
            app.change(4,'legacy',True)
        self.assertEqual(Settings(self.path).ports['4']['mode'],0x11)

    def test_edit_disabled_port_and_preserve_legacy(self):
        wanted=requested_config(dict(config(),mode=0x11),'limit',30)
        self.assertEqual(wanted['mode'],0x12)
        self.assertFalse(wanted['enabled'])
        wanted=requested_config(wanted,'legacy',False)
        self.assertEqual(wanted['mode'],2)


class WebTests(unittest.TestCase):
    def setUp(self):
        import ipaddress
        self.controller=Mock();self.controller.configure.return_value=dict(config(),port=1)
        self.controller.read_port.return_value=dict(config(),port=1)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        settings=Settings(Path(self.tmp.name)/'ports.json')
        settings.save({str(p):config() for p in range(1,13)})
        self.app=App(self.controller,settings)
        self.server=Server(('127.0.0.1',0),self.app,[ipaddress.ip_network('127.0.0.0/8')])
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.host='127.0.0.1:%d'%self.server.server_port

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def call(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request(method,path,body,headers or {})
        response=conn.getresponse();data=response.read();conn.close()
        return response.status,data

    def test_page_and_no_auth_read(self):
        status,data=self.call('GET','/');self.assertEqual(status,200);self.assertIn(b'ET2500 PoE control',data)
        status,data=self.call('GET','/api/state');self.assertEqual(status,200);self.assertTrue(json.loads(data)['stale'])
        self.controller.configure.assert_not_called()

    def test_static_assets_are_packaged(self):
        for path in ('/app.js', '/style.css', '/front-panel.png'):
            status, data = self.call('GET', path)
            self.assertEqual(status, 200, path)
            self.assertGreater(len(data), 100, path)
            if path.endswith('.png'):
                self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.controller.configure.assert_not_called()

    def test_clients_outside_allowlist_are_blocked(self):
        import ipaddress
        self.server.networks = [ipaddress.ip_network('198.51.100.0/24')]
        self.assertEqual(self.call('GET', '/api/state')[0], 403)
        self.controller.configure.assert_not_called()

    def test_cross_origin_and_dns_rebinding_blocked(self):
        body=json.dumps({'port':1,'action':'power','value':'on'})
        headers={'Content-Type':'application/json','X-PoE-Token':self.app.token,'Origin':'http://other.site'}
        self.assertEqual(self.call('POST','/api/port',body,headers)[0],403)
        self.assertEqual(self.call('GET','/api/state',headers={'Host':'other.site'})[0],403)
        self.controller.configure.assert_not_called()

    def test_valid_command_and_invalid_port(self):
        headers={'Content-Type':'application/json','X-PoE-Token':self.app.token,'Origin':'http://'+self.host}
        self.assertEqual(self.call('POST','/api/port',json.dumps({'port':99,'action':'power','value':'off'}),headers)[0],400)
        self.controller.configure.assert_not_called()
        self.assertEqual(self.call('POST','/api/port',json.dumps({'port':1,'action':'priority','value':'Low'}),headers)[0],200)
        self.controller.configure.assert_called_once()


if __name__=='__main__':unittest.main()
