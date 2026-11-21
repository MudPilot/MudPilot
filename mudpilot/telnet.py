"""Minimal telnet client (Python 3.13 removed telnetlib). Runs a reader thread and
hands decoded text to a callback. Handles IAC negotiation: agrees to SGA/ECHO,
answers TTYPE with ANSI and NAWS with 80x24, refuses everything else."""
from __future__ import annotations

import queue
import socket
import threading

from .cp437 import decode as _decode     # bytes → text happens here, as IBM code page 437 (see cp437.py)

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ECHO, SGA, TTYPE, NAWS = 1, 3, 24, 31


class TelnetClient:
    def __init__(self):
        self.sock: socket.socket | None = None
        self.events: queue.Queue = queue.Queue()   # ("data", str) | ("closed", reason)
        self._thread = None
        self._iac_state = 0
        self._sb = bytearray()
        self.server_echo = False

    @property
    def connected(self) -> bool:
        return self.sock is not None

    def connect(self, host: str, port: int, timeout: float = 15):
        self.close()
        self.adopt(socket.create_connection((host, port), timeout=timeout))

    def adopt(self, s):
        """Use a socket that's already connected (auto-reconnect connects in the background)."""
        self.close()
        s.settimeout(None)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.sock = s
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def close(self):
        s, self.sock = self.sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def send_line(self, text: str):
        self.send_raw(text.encode("cp437", errors="replace") + b"\r\n")

    def send_raw(self, data: bytes):
        if not self.sock:
            return
        try:
            self.sock.sendall(data.replace(bytes([IAC]), bytes([IAC, IAC])))
        except OSError as e:
            self.events.put(("closed", str(e)))
            self.close()

    def _cmd(self, *b):
        if self.sock:
            try:
                self.sock.sendall(bytes(b))
            except OSError:
                pass

    def _reader(self):
        sock = self.sock
        reason = "connection closed by host"
        try:
            while sock is self.sock and sock:
                data = sock.recv(8192)
                if not data:
                    break
                text = self._strip_iac(data)
                if text:
                    self.events.put(("data", _decode(text)))
        except OSError as e:
            reason = str(e) if self.sock else "disconnected"
        if sock is self.sock or self.sock is None:     # not a stale reader from a previous connection
            self.events.put(("closed", reason))
        if sock is self.sock:
            self.sock = None

    def _strip_iac(self, data: bytes) -> bytes:
        out = bytearray()
        for b in data:
            st = self._iac_state
            if st == 0:
                if b == IAC:
                    self._iac_state = 1
                elif b != 0:
                    out.append(b)
            elif st == 1:
                if b == IAC:
                    out.append(IAC); self._iac_state = 0
                elif b in (DO, DONT, WILL, WONT):
                    self._iac_state = b
                elif b == SB:
                    self._sb.clear(); self._iac_state = SB
                else:
                    self._iac_state = 0
            elif st in (DO, DONT, WILL, WONT):
                self._negotiate(st, b); self._iac_state = 0
            elif st == SB:
                if b == IAC:
                    self._iac_state = -1
                else:
                    self._sb.append(b)
            elif st == -1:
                if b == SE:
                    self._subneg(bytes(self._sb))
                    self._iac_state = 0
                else:
                    self._sb.append(b); self._iac_state = SB
        return bytes(out)

    def _negotiate(self, cmd, opt):
        if cmd == DO:
            if opt in (TTYPE, NAWS, SGA):
                self._cmd(IAC, WILL, opt)
                if opt == NAWS:
                    self._cmd(IAC, SB, NAWS, 0, 80, 0, 24, IAC, SE)
            else:
                self._cmd(IAC, WONT, opt)
        elif cmd == WILL:
            if opt in (ECHO, SGA):
                self._cmd(IAC, DO, opt)
                if opt == ECHO:
                    self.server_echo = True
            else:
                self._cmd(IAC, DONT, opt)
        elif cmd == WONT and opt == ECHO:
            self.server_echo = False

    def _subneg(self, sb: bytes):
        if len(sb) >= 2 and sb[0] == TTYPE and sb[1] == 1:   # SEND
            self._cmd(IAC, SB, TTYPE, 0, *b"ANSI", IAC, SE)
