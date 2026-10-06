import json
import socket

try:
    import ssl as tls
except ImportError:
    import tls

from ca_cert import ISRG_ROOT_X1


class HttpResponse:
    def __init__(self, status, reason, headers, body):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")


def _parse_https_url(url):
    if not url.startswith("https://"):
        raise ValueError("Sono accettati solo URL HTTPS")

    remainder = url[8:]
    slash = remainder.find("/")
    if slash < 0:
        authority = remainder
        path = "/"
    else:
        authority = remainder[:slash]
        path = remainder[slash:]

    if ":" in authority:
        host, port_text = authority.rsplit(":", 1)
        port = int(port_text)
    else:
        host = authority
        port = 443

    if not host:
        raise ValueError("Host HTTPS mancante")
    return host, port, path


def _read_body(stream, headers):
    transfer_encoding = headers.get("transfer-encoding", "").lower()
    if "chunked" in transfer_encoding:
        chunks = []
        while True:
            line = stream.readline()
            size = int(line.split(b";", 1)[0], 16)
            if size == 0:
                stream.readline()
                break
            chunks.append(stream.read(size))
            stream.read(2)
        return b"".join(chunks)

    content_length = headers.get("content-length")
    if content_length is not None:
        remaining = int(content_length)
        chunks = []
        while remaining:
            chunk = stream.read(min(remaining, 1024))
            if not chunk:
                raise OSError("Risposta HTTP interrotta")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    chunks = []
    while True:
        chunk = stream.read(1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def post_json(url, payload, headers=None, timeout=15):
    host, port, path = _parse_https_url(url)
    body = json.dumps(payload).encode("utf-8")

    request_headers = {
        "Host": host,
        "Connection": "close",
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "User-Agent": "BSG-MicroPython/1.0",
    }
    if headers:
        request_headers.update(headers)

    address = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
    raw_socket = socket.socket(address[0], socket.SOCK_STREAM, address[2])
    raw_socket.settimeout(timeout)

    secure_socket = None
    try:
        raw_socket.connect(address[-1])
        context = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
        context.verify_mode = tls.CERT_REQUIRED
        context.load_verify_locations(cadata=ISRG_ROOT_X1)
        secure_socket = context.wrap_socket(raw_socket, server_hostname=host)

        secure_socket.write(("POST %s HTTP/1.1\r\n" % path).encode())
        for name, value in request_headers.items():
            secure_socket.write(("%s: %s\r\n" % (name, value)).encode())
        secure_socket.write(b"\r\n")
        secure_socket.write(body)

        status_line = secure_socket.readline()
        parts = status_line.split(None, 2)
        if len(parts) < 2:
            raise ValueError("Risposta HTTP non valida")
        status = int(parts[1])
        reason = parts[2].strip().decode() if len(parts) > 2 else ""

        response_headers = {}
        while True:
            line = secure_socket.readline()
            if not line or line == b"\r\n":
                break
            name, value = line.split(b":", 1)
            response_headers[name.decode().lower()] = value.strip().decode()

        response_body = _read_body(secure_socket, response_headers)
        return HttpResponse(status, reason, response_headers, response_body)
    finally:
        if secure_socket is not None:
            secure_socket.close()
        else:
            raw_socket.close()
