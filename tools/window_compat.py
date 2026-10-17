"""Expose the legacy Delphi game form as an application window.

The zero-sized TApplication owner is unsuitable for window discovery. This
in-process compatibility adapter adds WS_EX_APPWINDOW to the visible TForm1.
It does not inject mouse/keyboard input or change the executable on disk.
"""
SCRIPT = r'''
const user32 = Process.getModuleByName('user32.dll');
const api = (name, result, args) => new NativeFunction(user32.getExportByName(name), result, args, 'stdcall');
const getClass = api('GetClassNameW', 'int', ['pointer','pointer','int']);
const visible = api('IsWindowVisible', 'bool', ['pointer']);
const getPid = api('GetWindowThreadProcessId', 'uint', ['pointer','pointer']);
const getStyle = api('GetWindowLongW', 'int', ['pointer','int']);
const setStyle = api('SetWindowLongW', 'int', ['pointer','int','int']);
const enumWindows = api('EnumWindows', 'bool', ['pointer','pointer']);
function expose() {
  const results = [];
  const name = Memory.alloc(512), pid = Memory.alloc(4);
  const callback = new NativeCallback((hwnd, unused) => {
    getPid(hwnd, pid);
    if (pid.readU32() !== Process.id || !visible(hwnd)) return 1;
    getClass(hwnd, name, 256);
    if (name.readUtf16String() !== 'TForm1') return 1;
    const before = getStyle(hwnd, -20);
    const wanted = before | 0x40000;
    if (before !== wanted) setStyle(hwnd, -20, wanted);
    const after = getStyle(hwnd, -20);
    results.push({hwnd:hwnd.toString(), before, after, success:after === wanted});
    return 1;
  }, 'bool', ['pointer','pointer'], 'stdcall');
  enumWindows(callback, ptr(0));
  return results;
}
rpc.exports = { expose };
const timer = setInterval(() => {
  const results = expose();
  if (results.length) {
    send({event:'game_window_compat', results});
    clearInterval(timer);
  }
}, 1000);
'''


def install(session, on_message=None):
    script = session.create_script(SCRIPT)
    if on_message:
        script.on('message', on_message)
    script.load()
    return script
