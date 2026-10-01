#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ET2500 PoE console. Standard library only; protocol mapping from Asterfusion.

Only API_BT_Share_workspace owns the UART during each bounded transaction.
Never invokes vendor initialization, LED/MMIO utilities or watchdog operations.
"""
import argparse
import collections
import datetime
import fcntl
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import threading
import time
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
PORT_MAP = (4, 5, 6, 7, 8, 9, 10, 11, 0, 1, 2, 3)
TWO_PAIR = {0x80, 0x81, 0x82, 0x83, 0x85, 0x87, 0x88, 0x90}
FOUR_PAIR = {0x84, 0x86, 0x89, 0x91}
NO_POWER = {0x06, 0x07, 0x08, 0x0c, 0x12, 0x1a, 0x1b, 0x1c, 0x1e,
            0x1f, 0x20, 0x22, 0x24, 0x25, 0x26, 0x34, 0x35, 0x36,
            0x43, 0x44, 0x45, 0x46, 0x48, 0x49, 0x4a, 0x4b, 0x4c, 0xa8}
LEGACY_ON = {0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x21, 0x22, 0x24, 0x25, 0x26, 0x27, 0x30}
LEGACY_OFF = {0, 1, 2, 3, 0x20, 0x23}
PRIORITIES = {1: 'Critical', 2: 'High', 3: 'Low'}


class ControllerError(Exception):
    pass


def frame_from_output(output, section):
    match = re.search(re.escape(section) + r'((?:\s*0x[0-9a-fA-F]{2})+)', output)
    if not match:
        raise ControllerError('Controller response is missing a frame')
    frame = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]{2})', match[1]))
    if len(frame) != 15 or sum(frame[:13]) != int.from_bytes(frame[13:], 'big'):
        raise ControllerError('Controller response has an invalid length or checksum')
    return frame


def validate_reply(output, request):
    sent = frame_from_output(output, 'send msg:')
    received = frame_from_output(output, 'read back:')
    # Vendor transport replaces the echo byte. Validate the actual sent echo.
    if sent[:1] + sent[2:13] != bytes(request[:1] + request[2:]):
        raise ControllerError('Transport sent an unexpected command')
    if received[1] != sent[1]:
        raise ControllerError('Controller reply does not match the request')
    if request[0] == 2 and received[0] != 3:
        raise ControllerError('Controller rejected the status request')
    if request[0] == 0 and (received[0] != 0x52 or received[2:4] != b'\x00\x00'):
        raise ControllerError('Controller rejected the setting (reply %s)' % received[:4].hex())
    return received


# Operation profiles describe configured limits, not measured consumption.
PROFILES = {0: '90 W / 30 W', 1: '60 W / 30 W', 2: '30 W', 3: '15 W'}
CONFIG_KEYS = {'enabled', 'mode', 'priority', 'cfg2', 'extra_power'}
STATUS_TEXT = {
    0x1A: 'Disabled by configuration', 0x1B: 'Detecting device',
    0x1C: 'Device signature not accepted', 0x1E: 'Underload / device disconnected',
    0x1F: 'Overload', 0x20: 'Power budget exceeded', 0x22: 'Applying settings',
    0x24: 'External voltage detected', 0x25: 'Detection / short-circuit fault',
    0x26: 'Discharged load', 0x34: 'Short circuit', 0x35: 'Over temperature',
    0x43: 'Classification error', 0xA7: 'Connection check failed', 0xA8: 'No device',
}


def detection(code):
    if code in {0x90, 0x91}:
        return 'Forced power'
    if code in {0x80, 0x82, 0x83, 0x84}:
        return 'Legacy / non-IEEE'
    if code in {0x85, 0x86}:
        return 'IEEE · single signature'
    if code in {0x87, 0x88, 0x89}:
        return 'IEEE · dual signature'
    if code == 0x81:
        return 'IEEE'
    return 'Not detected'


def profile(mode):
    base = mode & 0x0f
    return PROFILES.get(base, 'Unknown') if mode in set(range(4)) | set(range(0x10, 0x14)) else 'Special mode 0x%02X' % mode


def port_config(port):
    result = {key: port[key] for key in CONFIG_KEYS}
    validate_config(result)
    return result


def validate_config(value):
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS:
        raise ControllerError('Invalid saved port configuration')
    if type(value['enabled']) is not bool or type(value['mode']) is not int or value['mode'] not in set(range(4)) | set(range(0x10, 0x14)):
        raise ControllerError('Unsupported saved power mode; no force-power restoration allowed')
    if value['priority'] not in PRIORITIES.values():
        raise ControllerError('Invalid saved priority')
    for key in ('cfg2', 'extra_power'):
        if type(value[key]) is not int or not 0 <= value[key] < 255:
            raise ControllerError('Invalid saved controller parameter')


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.ports = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if set(data) != {'version', 'ports'} or data['version'] != 1 or not isinstance(data['ports'], dict) or set(data['ports']) != {str(p) for p in range(1, 13)}:
                    raise ValueError('Invalid settings schema')
                for value in data['ports'].values():
                    validate_config(value)
                self.ports = data['ports']
            except (ValueError, TypeError, ControllerError) as exc:
                raise ControllerError('Saved settings invalid; refusing to overwrite or apply them') from exc

    def save(self, ports):
        for value in ports.values():
            validate_config(value)
        data = json.dumps({'version': 1, 'ports': ports}, indent=2) + '\n'
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, prefix='.ports-', delete=False) as f:
                name = f.name
                os.chmod(name, 0o600)
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(name, self.path)
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            self.ports = ports
        except OSError as exc:
            raise ControllerError('Could not durably save settings; reload before retrying') from exc
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def initialize(self, controller):
        # Read and validate every port before changing any hardware.
        live = [controller.read_port(p) for p in range(1, 13)]
        configs = {str(p['port']): port_config(p) for p in live}
        if self.ports is None:
            self.save(configs)  # First installation adopts settings, including enabled empty ports.
            return 0
        count = 0
        for p in live:
            wanted = self.ports[str(p['port'])]
            if configs[str(p['port'])] != wanted:
                controller.configure(p['port'], wanted, before=p)
                count += 1
        return count


def link_info(index):
    path = Path('/sys/class/net') / ('Ethernet%d' % index)
    def read(name, default=''):
        try:
            return (path / name).read_text().strip()
        except OSError:
            return default
    carrier = read('carrier') == '1'
    speed = read('speed')
    return {'link': carrier, 'speed_mbps': int(speed) if carrier and speed.isdigit() else None,
            'duplex': read('duplex') if carrier else None}


class Controller:
    def __init__(self, binary):
        self.binary = binary

    def transact(self, request):
        try:
            result = subprocess.run([self.binary, *('%02x' % b for b in request)],
                                    capture_output=True, text=True, timeout=2.5, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ControllerError('Controller timeout; refresh state before retrying a change') from exc
        except OSError as exc:
            raise ControllerError('PoE transport unavailable') from exc
        if result.returncode:
            raise ControllerError('PoE transport exited with code %d' % result.returncode)
        return validate_reply(result.stdout, request)

    def query(self, port, kind):
        return self.transact([2, 0x80, 5, kind, PORT_MAP[port-1], *([0x4e]*8)])

    def read_port(self, port):
        status = self.query(port, 0xc0)
        measurement = self.query(port, 0xc5)
        code, mode = status[2], status[5]
        state = ('supplying' if code in TWO_PAIR | FOUR_PAIR else
                 'disabled' if code == 0x1a else 'idle' if code in NO_POWER else 'unknown')
        return {'port': port, 'interface': 'Ethernet%d' % (port-1),
                'role': 'Copper',
                'state': state, 'status_code': '0x%02X' % code, 'mode': mode,
                'enabled': {0: False, 1: True}.get(status[3] & 0x0f),
                'cfg2': status[4], 'extra_power': status[6],
                'legacy': mode in LEGACY_ON if mode in LEGACY_ON | LEGACY_OFF else None,
                'profile': profile(mode), 'detection': detection(code),
                'status_text': STATUS_TEXT.get(code, detection(code) if code in TWO_PAIR | FOUR_PAIR else 'Controller status 0x%02X' % code),
                'pair_set': 'Alternative A' if code == 0x82 else 'Not reported',
                'pairs': 4 if code in FOUR_PAIR else 2 if code in TWO_PAIR else None,
                'power_w': round(int.from_bytes(measurement[6:8], 'big') / 10, 1),
                'voltage_v': round(int.from_bytes(measurement[9:11], 'big') / 10, 1),
                'current_ma': int.from_bytes(measurement[4:6], 'big'),
                'limit_w': {0: 90, 1: 60, 2: 30, 3: 15}.get(mode & 15), 'priority': PRIORITIES.get(status[7], 'Unknown'),
                'sampled_at': time.time(), **link_info(port-1)}

    def configure(self, port, wanted, before=None):
        validate_config(wanted)
        before = before if before is not None else self.read_port(port)
        current = port_config(before)
        if current == wanted:
            return before
        request = [0, 0x80, 5, 0xc0, PORT_MAP[port-1], 0x0f, 0xff, 0xff, 0, 0xff, 0x4e, 0x4e, 0x4e]
        if current['enabled'] != wanted['enabled']:
            request[5] = int(wanted['enabled'])
        if current['cfg2'] != wanted['cfg2']:
            request[6] = wanted['cfg2']
        if any(current[k] != wanted[k] for k in ('mode', 'extra_power')):
            request[7], request[8] = wanted['mode'], wanted['extra_power']
        if current['priority'] != wanted['priority']:
            request[9] = {v:k for k,v in PRIORITIES.items()}[wanted['priority']]
        self.transact(request)
        after = self.read_port(port)
        if port_config(after) != wanted:
            raise ControllerError('Controller settings differ from saved settings; reload before retrying')
        return after


def requested_config(before, action, value):
    wanted = port_config(before)
    if action == 'power':
        wanted['enabled'] = value == 'on'
    elif action == 'priority':
        wanted['priority'] = value
    elif action == 'limit':
        wanted['mode'] = {15:3, 30:2, 60:1}[value] | (wanted['mode'] & 0x10)
        wanted['extra_power'] = 0
    elif action == 'legacy':
        wanted['mode'] = (wanted['mode'] & 0x0f) | (0x10 if value else 0)
    return wanted


def validate_action(body):
    if not isinstance(body, dict) or set(body) != {'port', 'action', 'value'}:
        raise ValueError('Expected port, action and value')
    port, action, value = body['port'], body['action'], body['value']
    if type(port) is not int or not 1 <= port <= 12:
        raise ValueError('Port must be an integer from 1 to 12')
    if action == 'power' and isinstance(value, str) and value in ('on', 'off'):
        return port, action, value
    if action == 'priority' and isinstance(value, str) and value in PRIORITIES.values():
        return port, action, value
    if action == 'legacy' and type(value) is bool:
        return port, action, value
    if action == 'limit' and type(value) is int and value in (15, 30, 60):
        return port, action, value
    raise ValueError('Unsupported setting')


class App:
    def __init__(self, controller, settings):
        self.controller = controller
        self.settings = settings
        self.hardware = threading.Lock()
        self.data_lock = threading.Lock()
        self.ports = []
        self.error = None
        self.updated = None
        self.events = collections.deque(maxlen=20)
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.last_view = time.monotonic()
        self.token = secrets.token_urlsafe(32)

    def snapshot(self):
        self.last_view = time.monotonic()
        with self.data_lock:
            ports = []
            for p in self.ports:
                saved = self.settings.ports.get(str(p['port']))
                ports.append(dict(p, saved=saved, settings_match=saved == {k:p.get(k) for k in CONFIG_KEYS}))
            return {'ports': ports, 'persistence': 'Saved settings are restored when the service starts',
                    'uplinks': [{'port': i+1, 'interface': 'Ethernet%d' % i, **link_info(i)} for i in range(12, 16)],
                    'error': self.error, 'updated_at': self.updated,
                    'stale': self.updated is None or time.time()-self.updated > 25,
                    'events': list(self.events), 'csrf': self.token}

    def poll(self):
        while not self.stop.is_set():
            try:
                with self.hardware:
                    ports = [self.controller.read_port(p) for p in range(1, 13)]
                    with self.data_lock:
                        self.ports, self.error, self.updated = ports, None, time.time()
            except Exception as exc:
                logging.exception('PoE refresh failed')
                with self.data_lock:
                    self.error = str(exc) if isinstance(exc, ControllerError) else 'Could not refresh the controller'
            delay = 8 if time.monotonic()-self.last_view < 30 else 60
            self.wake.wait(delay)
            self.wake.clear()

    def change(self, port, action, value):
        if not self.hardware.acquire(timeout=6):
            raise ControllerError('Controller busy; please retry shortly')
        try:
            before = self.controller.read_port(port)
            wanted = requested_config(self.settings.ports[str(port)], action, value)
            configs = dict(self.settings.ports)
            configs[str(port)] = wanted
            # Persist intent BEFORE hardware: power loss cannot lose an accepted change.
            with self.data_lock:
                self.settings.save(configs)
            try:
                after = self.controller.configure(port, wanted, before=before)
            except ControllerError as exc:
                raise ControllerError('Settings saved, but hardware confirmation failed. Reload to inspect; saved settings will be retried at service startup. ' + str(exc)) from exc
            with self.data_lock:
                self.ports = [after if p['port'] == port else p for p in self.ports]
                self.events.appendleft({'time': time.time(), 'text': 'Port %d · %s → %s' % (port, action, value)})
            logging.info('Port %d: %s = %s (acknowledged)', port, action, value)
            return after
        finally:
            self.hardware.release()
            self.wake.set()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, app, networks):
        self.app, self.networks = app, networks
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'CN102-PoE'
    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def log_message(self, fmt, *args):
        if len(args) > 1 and str(args[1]) != '200':
            logging.info('%s %s', self.client_address[0], fmt % args)

    def send(self, code, payload, content_type='application/json'):
        data = json.dumps(payload).encode() if content_type == 'application/json' else payload
        self.send_response(code)
        for key, val in [('Content-Type', content_type), ('Content-Length', str(len(data))),
                         ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                         ('X-Frame-Options', 'DENY'), ('Referrer-Policy', 'no-referrer'),
                         ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")]:
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        host, port = self.server.server_address
        if self.headers.get('Host') != '%s:%s' % (host, port):
            self.send(403, {'error': 'Use the management IP and port directly'})
            return False
        if not any(ipaddress.ip_address(self.client_address[0]) in n for n in self.server.networks):
            self.send(403, {'error': 'Management network only'})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        if self.path == '/api/state':
            self.send(200, self.server.app.snapshot())
            return
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/front-panel.png': ('front-panel-no-antennas.png', 'image/png'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path in assets:
            filename, mime = assets[self.path]
            self.send(200, (ROOT/filename).read_bytes(), mime)
        else:
            self.send(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.allowed():
            return
        expected = 'http://%s:%s' % self.server.server_address
        if (self.headers.get('Origin') != expected or
            not secrets.compare_digest(self.headers.get('X-PoE-Token', ''), self.server.app.token)):
            self.send(403, {'error': 'Reload this page before making a change'})
            return
        if self.path != '/api/port':
            self.send(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 512 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Expected a small JSON request')
            args = validate_action(json.loads(self.rfile.read(length)))
        except (ValueError, TypeError, UnicodeError):
            self.send(400, {'error': 'Invalid port or setting'})
            return
        try:
            port = self.server.app.change(*args)
            self.send(200, {'port': port, 'message': 'Settings saved and confirmed. Power detection may take a few seconds.'})
        except ControllerError as exc:
            self.send(502, {'error': str(exc)})
        except Exception:
            logging.exception('Control failed')
            self.send(500, {'error': 'Change could not be confirmed; refresh before retrying'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8088)
    parser.add_argument('--allow', action='append', default=[])
    parser.add_argument('--backend', default='/usr/bin/API_BT_Share_workspace')
    parser.add_argument('--state-file', default='/var/lib/cn102-poe/ports.json')
    parser.add_argument('--lock', default='/run/cn102-poe/transport.lock')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    lock = open(args.lock, 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    controller = Controller(args.backend)
    settings = Settings(args.state_file)
    restored = settings.initialize(controller)
    logging.info('Persistent settings ready; restored %d changed ports', restored)
    app = App(controller, settings)
    server = Server((args.bind, args.port), app,
                    [ipaddress.ip_network(n) for n in (args.allow or ['127.0.0.1/32'])])
    worker = threading.Thread(target=app.poll, daemon=True)
    worker.start()
    def stop(*_):
        app.stop.set()
        app.wake.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.info('Listening on http://%s:%d; no authentication; management network only', args.bind, args.port)
    try:
        server.serve_forever()
    finally:
        app.stop.set()
        app.wake.set()
        server.server_close()
        worker.join(timeout=4)
        lock.close()


if __name__ == '__main__':
    main()
