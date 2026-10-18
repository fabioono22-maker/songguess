"""Servidor local do Songguess. Sem dependências: só Python 3.
Uso:  python server.py   (e o navegador abre sozinho)
"""
import json, os, re, socket, threading, webbrowser, urllib.request, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
PORT = int(os.environ.get("PORT", 8000))  # hospedagens na nuvem definem PORT
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


STATIC = {
    "/manifest.webmanifest": "application/manifest+json",
    "/sw.js": "text/javascript; charset=utf-8",
    "/icon-192.png": "image/png",
    "/icon-512.png": "image/png",
    "/icon-maskable-512.png": "image/png",
    "/apple-touch-icon.png": "image/png",
}


def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def find(o, key, kind):
    """Procura recursivamente uma chave cujo valor seja do tipo `kind`."""
    if isinstance(o, dict):
        if isinstance(o.get(key), kind):
            return o[key]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = find(v, key, kind)
            if r:
                return r
    return None


def from_embed(pid):
    html = get(f"https://open.spotify.com/embed/playlist/{pid}")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("O Spotify não devolveu os dados da playlist (ela é pública?)")
    data = json.loads(m.group(1))
    tracks = find(data, "trackList", list) or []
    songs = [{
        "title": t.get("title", ""),
        "artist": (t.get("subtitle") or "").replace("\xa0", " "),
        "url": (t.get("audioPreview") or {}).get("url"),
    } for t in tracks]
    return songs, find(data, "accessToken", str)


def from_api(pid, token):
    """Tenta pegar a playlist inteira (mais de 100 faixas) com o token anônimo do embed."""
    songs = []
    url = (f"https://api.spotify.com/v1/playlists/{pid}/tracks?limit=100"
           "&fields=next,items(track(name,preview_url,artists(name)))")
    while url and len(songs) < 1000:
        d = json.loads(get(url, {"Authorization": f"Bearer {token}"}))
        for it in d.get("items", []):
            t = it.get("track")
            if t and t.get("name"):
                songs.append({
                    "title": t["name"],
                    "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                    "url": t.get("preview_url"),
                })
        url = d.get("next")
    return songs


def load_playlist(pid):
    songs, token = from_embed(pid)
    if token:
        try:
            full = from_api(pid, token)
            if len(full) > len(songs):
                songs = full
        except Exception:
            pass  # fica com as faixas do embed
    if not songs:
        raise RuntimeError("Playlist vazia ou privada")
    return songs


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self.send(200, (HERE / "songguess.html").read_bytes(), "text/html; charset=utf-8")
        elif u.path in STATIC:
            self.send(200, (HERE / u.path[1:]).read_bytes(), STATIC[u.path])
        elif u.path == "/api/playlist":
            pid = urllib.parse.parse_qs(u.query).get("id", [""])[0]
            if not re.fullmatch(r"[A-Za-z0-9]+", pid):
                return self.send(400, json.dumps({"error": "ID de playlist inválido"}))
            try:
                self.send(200, json.dumps(load_playlist(pid)))
            except Exception as e:
                self.send(502, json.dumps({"error": str(e)}))
        else:
            self.send(404, json.dumps({"error": "não encontrado"}))

    def log_message(self, *a):
        pass


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as k:
            k.connect(("8.8.8.8", 80))  # não envia nada, só descobre a interface de rede
            return k.getsockname()[0]
    except Exception:
        return None


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # aceita conexões da rede local
    ip = lan_ip()
    print(f"No computador:  http://127.0.0.1:{PORT}")
    if ip:
        print(f"No celular:     http://{ip}:{PORT}   (mesmo Wi-Fi)")
    print("Ctrl+C para parar")
    if not os.environ.get("PORT"):
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
