const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../dashboard.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new vm.Script(script); // Check all dashboard JavaScript, including polling.
const handlers = script.split('\n').filter(line =>
  line.startsWith('let saving=') || line.startsWith('async function api(') ||
  line.startsWith('async function reconnectAfterRestart(') || line.startsWith('for(const id of'));

async function exercise(fail) {
  const forms = Object.fromEntries(['wifi-form', 'configuration', 'clock-form', 'runtime-form'].map(id =>
    [id, {button: {disabled: false}, querySelector() {return this.button;}}]));
  const notices = [], timers = [], calls = [];
  let reloads = 0;
  const context = vm.createContext({
    $: id => forms[id], notice: text => notices.push(text),
    FormData: class { *[Symbol.iterator]() {yield ['section', 'integrations'];} },
    URLSearchParams, AbortController, TypeError,
    setTimeout: (callback, delay) => {timers.push({callback, delay}); return timers.length;},
    clearTimeout: () => {}, location: {reload: () => reloads++},
    fetch: async (url, options) => {
      calls.push({url, options});
      if (options.method === 'POST') {
        assert.equal(vm.runInContext('saving', context), true);
        if (fail) throw new TypeError('Failed to fetch');
        return {ok: true, json: async () => ({message: 'Servizi salvati', restart: true})};
      }
      return {ok: true, json: async () => ({firmware_version: '0.2.0'})};
    },
  });
  vm.runInContext(handlers.join('\n'), context);
  vm.runInContext('settingsLoaded=true', context);
  await forms.configuration.onsubmit({preventDefault() {}, currentTarget: forms.configuration});
  assert.equal(vm.runInContext('saving', context), false);
  assert.equal(calls[0].url, '/api/config');
  if (fail) {
    assert.equal(forms.configuration.button.disabled, false);
    assert.equal(vm.runInContext('restarting', context), false);
    assert.match(notices[0], /riprova/);
    assert.equal(reloads, 0);
  } else {
    assert.equal(forms.configuration.button.disabled, true);
    assert.equal(vm.runInContext('restarting', context), true);
    const reconnect = timers.find(timer => timer.delay === 7000);
    await reconnect.callback();
    assert.equal(calls[1].url, '/api/readings');
    assert.equal(reloads, 1);
  }
}

function settingsFields() {
  const names = {
    'wifi-form': ['ssid', 'network_hidden', 'clear_wifi_password', 'password'],
    configuration: ['wu_enabled', 'wu_station_id', 'wu_station_key', 'wu_mode', 'wu_interval', 'wu_utc_offset',
                    'amms_enabled', 'transport', 'auth_mode', 'station_id', 'key_id', 'url', 'timeout_seconds',
                    'amms_interval', 'mqtt_host', 'mqtt_port', 'mqtt_keepalive', 'mqtt_ca_cert', 'secret_hex', 'token'],
    'clock-form': ['timezone', 'ntp_enabled', 'dst_auto'],
    'runtime-form': ['poll_interval_ms', 'serial_interval_seconds'],
  };
  const checkboxes = ['wu_enabled', 'amms_enabled', 'network_hidden', 'clear_wifi_password', 'ntp_enabled', 'dst_auto'];
  const forms = Object.fromEntries(Object.entries(names).map(([id, values]) => [id, {elements:
    Object.fromEntries(values.map(name => [name, {name, type: checkboxes.includes(name) ? 'checkbox' : 'text', value: '', checked: false}]))}]));
  const fields = Object.values(forms.configuration.elements);
  const context = vm.createContext({$: id => forms[id], document: {
    querySelectorAll: selector => fields.filter(field => selector.includes('wunderground')
      ? field.name.startsWith('wu_') : !field.name.startsWith('wu_')),
  }});
  vm.runInContext(script.split('\n').filter(line =>
    line.startsWith('function applySettings(') || line.startsWith('function updateServiceFields(')).join('\n'), context);
  context.settings = {
    wifi: {ssid: 'Casa <&>', has_password: true, password: 'must-not-fill'},
    weather_underground: {enabled: true, station_id: 'ISTATION', mode: 'standard', upload_interval_seconds: 10, station_key: 'must-not-fill'},
    amms: {enabled: false, transport: 'mqtt', url: 'invalid URL', secret_hex: 'must-not-fill'},
    runtime: {poll_interval_ms: 25, serial_interval_seconds: 10}, clock: {timezone: 'Europe/Rome'},
  };
  vm.runInContext('applySettings(settings)', context);
  assert.equal(forms['wifi-form'].elements.ssid.value, 'Casa <&>');
  assert.equal(forms.configuration.elements.wu_station_id.value, 'ISTATION');
  assert.equal(forms.configuration.elements.wu_enabled.checked, true);
  assert.equal(forms.configuration.elements.wu_station_id.disabled, false);
  assert.equal(forms.configuration.elements.url.disabled, true);
  assert.equal(forms.configuration.elements.amms_enabled.disabled, undefined);
  assert.equal(forms.configuration.elements.wu_station_key.value, '');
  assert.equal(forms.configuration.elements.secret_hex.value, '');
  assert.equal(forms['wifi-form'].elements.password.value, '');
}

(async () => {
  settingsFields();
  await exercise(false);
  await exercise(true);
  console.log('Dashboard JavaScript: syntax, save confirmation, reconnect and network failure OK');
})().catch(error => {console.error(error); process.exitCode = 1;});
