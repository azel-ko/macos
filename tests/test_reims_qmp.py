import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reims_qmp", ROOT / "setup/reims_qmp.py")
qmp_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qmp_module)


class QMPTests(unittest.TestCase):
    def peer(self, replies):
        stream = MagicMock()
        stream.readline.side_effect = [
            (json.dumps(item) + "\r\n").encode() for item in
            [{"QMP": {}}, {"return": {}, "id": 1}] + replies
        ] + [b""]
        sock = MagicMock()
        sock.makefile.return_value = stream
        return sock, stream

    def test_events_do_not_displace_response_and_hmp_carries_cpu_index(self):
        sock, stream = self.peer([
            {"event": "STOP", "data": {}}, {"return": "CPU #2", "id": 2}])
        with patch.object(qmp_module.socket, "socket", return_value=sock):
            with qmp_module.QMP("private/qmp.sock") as qmp:
                self.assertEqual(qmp.hmp("info registers", 2), "CPU #2")
                self.assertEqual(qmp.events[0]["event"], "STOP")
        request = json.loads(stream.write.call_args_list[-1].args[0])
        self.assertEqual(request["arguments"], {"command-line": "info registers", "cpu-index": 2})
        stream.close.assert_called_once()
        sock.close.assert_called_once()

    def test_error_wrong_id_and_eof_are_not_success(self):
        for reply, error in [
            ({"error": {"class": "GenericError", "desc": "VM shutdown"}, "id": 2}, RuntimeError),
            ({"return": {}, "id": 99}, RuntimeError),
            (None, EOFError),
        ]:
            with self.subTest(reply=reply):
                sock, _ = self.peer([] if reply is None else [reply])
                with patch.object(qmp_module.socket, "socket", return_value=sock):
                    with qmp_module.QMP("private/qmp.sock") as qmp:
                        with self.assertRaises(error):
                            qmp.execute("cont")

    def test_panic_addresses_are_exact_nonzero_and_deduplicated(self):
        serial = "CR2: 0x0 CR2: 0xffffff8001234000 Spinlock[0xffffff8001234000] CR3: 0x1234"
        self.assertEqual(qmp_module.panic_addresses(serial), [0xffffff8001234000])

    def test_identification_requires_exact_disk_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "qemu.pid").write_text("42")
            original = Path.read_bytes
            for suffix, valid in [("", True), ("-another-vm", False)]:
                cmdline = f"qemu-system-x86_64\0-drive\0if=none,file={run}/macos.qcow2{suffix},format=qcow2\0".encode()
                def read(path):
                    return cmdline if str(path) == "/proc/42/cmdline" else original(path)
                with patch.object(Path, "read_bytes", read):
                    if valid:
                        self.assertEqual(qmp_module.identified_run(run), run)
                    else:
                        with self.assertRaises(RuntimeError):
                            qmp_module.identified_run(run)
