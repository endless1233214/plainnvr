const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function watchdog() {
  let now = 0;
  let tick;
  let reconnects = 0;
  const player = {ready: true, video: {currentTime: 0, paused: false}, stop() { reconnects++; }};
  const document = {hidden: false, addEventListener() {}, getElementById(id) {
    return id === 'go2rtcLive' ? player : {};
  }};
  const context = vm.createContext({document, performance: {now: () => now},
    setInterval(callback) { tick = callback; return 1; }, clearInterval() {},
    setTimeout() { return 2; }, clearTimeout() {}, console});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8'), context);
  vm.runInContext('Object.assign(state, {liveActive:true, liveCameraId:"cam", liveBackend:"go2rtc"}); startLiveWatchdog({id:"cam",name:"Camera"});', context);
  return {player, document, step(ms) { now = ms; tick(); }, reconnects: () => reconnects};
}

test('a stream that freezes after playing reconnects its viewer', () => {
  const view = watchdog();
  view.step(0);
  view.player.video.currentTime = 1;
  view.step(1000);
  view.step(7100);
  assert.equal(view.reconnects(), 1);
});

test('healthy playback keeps the same connection', () => {
  const view = watchdog();
  for (let i = 0; i < 20; i++) {
    view.player.video.currentTime = i;
    view.step(i * 1000);
  }
  assert.equal(view.reconnects(), 0);
});

test('user pause and background tabs do not trigger recovery loops', () => {
  const view = watchdog();
  view.player.video.paused = true;
  view.step(20000);
  view.player.video.paused = false;
  view.document.hidden = true;
  view.step(40000);
  view.document.hidden = false;
  view.step(41000);
  assert.equal(view.reconnects(), 0);
});

test('startup gets a grace period, then retries if no media arrives', () => {
  const view = watchdog();
  view.player.ready = false;
  view.step(0);
  view.step(11000);
  assert.equal(view.reconnects(), 0);
  view.step(13000);
  assert.equal(view.reconnects(), 1);
});

test('MSE queue overflow reconnects without throwing or dropping random bytes', () => {
  let closed = 0;
  const sb = {updating: true, addEventListener() {}};
  class MediaSource { addEventListener() {} addSourceBuffer() { return sb; } }
  const context = vm.createContext({HTMLElement: class {}, MediaSource,
    WebSocket: {CONNECTING: 0, OPEN: 1, CLOSED: 3},
    window: {}, URL: {createObjectURL: () => 'blob:test'}, console});
  const source = fs.readFileSync(path.join(__dirname, '../static/vendor/go2rtc/video-rtc.js'), 'utf8');
  vm.runInContext(source.replace('export class VideoRTC', 'class VideoRTC') + '\nglobalThis.VideoRTC = VideoRTC;', context);
  const player = new context.VideoRTC();
  player.video = {play: () => Promise.resolve()};
  player.ws = {close() { closed++; }};
  player.onmessage = {};
  player.onmse();
  player.onmessage.mse({type:'mse',value:'video/mp4; codecs="avc1.640029"'});
  assert.doesNotThrow(() => {
    player.ondata(new Uint8Array(2 * 1024 * 1024).buffer);
    player.ondata(new Uint8Array(1).buffer);
    player.ondata(new Uint8Array(1).buffer);
  });
  assert.equal(closed, 1);
});
