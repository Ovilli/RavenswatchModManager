"""`rsmm editor`: the item, talent, ability and map editors behind one page.

    app.py       routing, the write token, page rendering (transport-free)
    server.py    HTTP on 127.0.0.1 for `rsmm editor`
    bridge.py    the same app without a socket, for the web editor (Pyodide)
    content.py   Items + Talents     abilities.py  Abilities     maps.py  Map
    pages/       one .html per editor, plus common.css / common.js
    static/      three.js, vendored for the map's 3D view

An editor is a module with MOUNT, PAGE and ROUTES; `app` serves each under
``/<MOUNT>/``. Pages use relative URLs only (``api/...``), which is what lets
one page run at a mount of the local server and inside the web editor.
"""
