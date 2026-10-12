"""Desktop preview: synthetic readings, configuration kept only in RAM."""
import argparse
import json
import math
import pathlib
import sys
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules'))
sys.modules['network'] = types.SimpleNamespace(WLAN=lambda _: None)
import config_store
import wifi_manager
import dashboard_service
import gc
gc.mem_free = lambda: 145000
from station_clock import clock_status

config = config_store._copy_defaults()
config['wifi']['ssid'] = 'Anteprima locale'
state = dict(sensors={}, stations={}, received=0, unrecognized=0, age_seconds=0,
             firmware_version=wifi_manager.FIRMWARE_VERSION, firmware_stage='ANTEPRIMA · dati simulati',
             sensor_id=12345, model='Bresser 7-in-1', rssi=-67, battery_ok=True,
             error='', wifi_status='connesso', wu_status='disabilitato', amms_status='disabilitato',
             heap_free=145000, core_temperature=48.3, radio_diagnostics={'rx_active': True})
service = dashboard_service.DashboardService(config, None, state)
# No disk writes and no hardware actions in this preview.
dashboard_service.save = lambda candidate: None
wifi_manager.save = lambda candidate: None
service.scan = lambda: None
service.networks = [dict(ssid='Anteprima locale', channel=6, rssi=-48, security='WPA2-PSK', security_code=3, hidden=False, bssid='00:11:22:33:44:55'), dict(ssid='Rete ospiti', channel=11, rssi=-65, security='Aperta', security_code=0, hidden=False, bssid='00:11:22:33:44:66'), dict(ssid='', channel=1, rssi=-78, security='WPA2-PSK', security_code=3, hidden=True, bssid='00:11:22:33:44:77')]
service.scan_message = 'Reti simulate per anteprima'
time.ticks_ms = lambda: int(time.monotonic()*1000)
start = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    def handle_request(self):
        age = time.monotonic()-start
        values = dict(temperature=21+math.sin(age/20)*2, humidity=64+math.sin(age/25)*5,
                      wind_speed=8+math.sin(age/9)*3, wind_gust=15+math.sin(age/12)*4,
                      wind_direction=(225+age)%360, precipitation=3.6, uv_index=2.4, light_lux=18500+math.sin(age/30)*3000)
        if args.model == '5':
            values.pop('uv_index')
            values.pop('light_lux')
        state['model'] = 'Bresser ' + args.model + '-in-1'
        state.update(sensors=values, received=int(age/2)+1, uptime_seconds=int(age), clock=dict(clock_status(config['clock']), status='Anteprima desktop'))
        state['stations'] = {'bresser_'+args.model+'in1:12345:0': dict(model=state['model'], sensors=values, received=state['received'], age_seconds=0, rssi=-67, battery_ok=True)}
        state['network'] = dict(mode='Anteprima desktop', ssid=config['wifi']['ssid'], ip='127.0.0.1', netmask='255.0.0.0', gateway='—', dns='—', ap_ssid='Bresser Gateway', ap_ip='192.168.4.1', rssi=-48)
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        raw = (self.command+' '+self.path+' HTTP/1.1\r\n').encode()
        raw += ''.join(k+': '+v+'\r\n' for k,v in self.headers.items()).encode()+b'\r\n'+body
        # Preview NTP request does not start a hardware thread.
        response = wifi_manager._ap_response(raw, state, config, service)
        self.wfile.write(response)

    do_GET = handle_request
    do_POST = handle_request
    def log_message(self, *_):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--model', choices=['5', '7'], default='7', help='Simulated sensor model')
    args = parser.parse_args()
    print('Anteprima con dati simulati: http://127.0.0.1:%d' % args.port, flush=True)
    ThreadingHTTPServer.allow_reuse_address = False
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
