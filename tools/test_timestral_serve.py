# SPDX-License-Identifier: Apache-2.0
"""A model served over a Unix socket (`timestral/serve.py`) and reached through
`sdk/tsfm.Remote`: the same forecast and receipt as the model itself, with the stand-in
model of `sdk/test_tsfm.py`."""
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, "timestral"))
import serve  # noqa: E402
import test_tsfm as T  # noqa: E402
import tsfm as TS  # noqa: E402
from ids import uuid7  # noqa: E402
from project import State  # noqa: E402


class TestAServedModel(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "tsfm.sock")
        self.server = serve.make_server(self.path, T.FakeModel())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()

    def test_the_same_forecast_and_receipt_as_the_model_itself(self):
        s, bed = State(), uuid7()
        top = T.probe(s, bed, 0.05, [0.30 - 0.001 * h for h in range(60)])
        mid = T.probe(s, bed, 0.10, [0.28 - 0.001 * h if h % 7 else None for h in range(40)])
        args = (s, mid.id, {"probe at 5 cm": top.id}, T.T0 + 40 * T.HOUR, 20, T.T0 + 60 * T.HOUR)
        remote = TS.Remote(self.path)
        try:
            far, far_receipt = TS.run(remote, *args, context_h=40)
        finally:
            remote.close()
        near, near_receipt = TS.run(T.FakeModel(), *args, context_h=40)
        self.assertEqual(far.quantiles, near.quantiles)
        self.assertEqual(far.levels, near.levels)
        self.assertEqual(far_receipt, near_receipt, "the server's model, weights and package")

    def test_an_error_is_said_and_the_server_stays_up(self):
        remote = TS.Remote(self.path)
        try:
            with self.assertRaises(RuntimeError):
                remote.forecast([], [], 3)
            self.assertEqual(remote.forecast([0.3], [], 1), T.FakeModel().forecast([0.3], [], 1))
        finally:
            remote.close()


if __name__ == "__main__":
    unittest.main()
