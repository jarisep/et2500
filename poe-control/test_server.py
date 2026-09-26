# SPDX-License-Identifier: Apache-2.0
import http.client
import json
import threading
import unittest
from unittest.mock import Mock
from server import (Controller, ControllerError, App, Server, validate_action,
                    validate_reply, PORT_MAP)


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

    def test_unsupported_power_limit_never_writes(self):
        c=Controller('/unused');c.transact=Mock()
        for pairs,mode,watts in [(None,1,30),(2,1,60),(4,255,30)]:
            c.read_port=Mock(return_value={'pairs':pairs,'mode':mode})
            with self.assertRaises(ControllerError):c.apply(1,'limit',watts)
        c.transact.assert_not_called()

    def test_write_preserves_other_settings_and_reads_back(self):
        c=Controller('/unused');c.transact=Mock()
        c.read_port=Mock(side_effect=[{'pairs':4,'mode':0x11},{'mode':0x12}])
        c.apply(12,'limit',30)
        self.assertEqual(c.transact.call_args.args[0],[0,0x80,5,0xc0,3,0x0f,0xff,0x12,0,0x4e,0x4e,0x4e,0x4e])

    def test_two_pair_30w_does_not_select_four_pair_90w_mode(self):
        c=Controller('/unused');c.transact=Mock()
        c.read_port=Mock(side_effect=[{'pairs':2,'mode':0},{'mode':2}])
        c.apply(1,'limit',30)
        self.assertEqual(c.transact.call_args.args[0][7],2)


class WebTests(unittest.TestCase):
    def setUp(self):
        import ipaddress
        self.controller=Mock();self.controller.apply.return_value={'port':1}
        self.app=App(self.controller)
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
        self.controller.apply.assert_not_called()

    def test_static_assets_are_packaged(self):
        for path in ('/app.js', '/style.css', '/front-panel.png'):
            status, data = self.call('GET', path)
            self.assertEqual(status, 200, path)
            self.assertGreater(len(data), 100, path)
            if path.endswith('.png'):
                self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.controller.apply.assert_not_called()

    def test_clients_outside_allowlist_are_blocked(self):
        import ipaddress
        self.server.networks = [ipaddress.ip_network('198.51.100.0/24')]
        self.assertEqual(self.call('GET', '/api/state')[0], 403)
        self.controller.apply.assert_not_called()

    def test_cross_origin_and_dns_rebinding_blocked(self):
        body=json.dumps({'port':1,'action':'power','value':'on'})
        headers={'Content-Type':'application/json','X-PoE-Token':self.app.token,'Origin':'http://other.site'}
        self.assertEqual(self.call('POST','/api/port',body,headers)[0],403)
        self.assertEqual(self.call('GET','/api/state',headers={'Host':'other.site'})[0],403)
        self.controller.apply.assert_not_called()

    def test_valid_command_and_invalid_port(self):
        headers={'Content-Type':'application/json','X-PoE-Token':self.app.token,'Origin':'http://'+self.host}
        self.assertEqual(self.call('POST','/api/port',json.dumps({'port':99,'action':'power','value':'off'}),headers)[0],400)
        self.controller.apply.assert_not_called()
        self.assertEqual(self.call('POST','/api/port',json.dumps({'port':1,'action':'priority','value':'Low'}),headers)[0],200)
        self.controller.apply.assert_called_once_with(1,'priority','Low')


if __name__=='__main__':unittest.main()
