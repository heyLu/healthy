import unittest

from healthy import ConnectionInfo, parse_ss_tip, read_net_per_process


class TestParseSSTip(unittest.TestCase):
    def test_example1(self):
        example1 = (
            'ESTAB 0      0                               '
            '192.168.43.58:53056               194.35.102.50:443 '
            'users:(("firefox-bin",pid=1367,fd=7)) '
            'cubic wscale:7,7 rto:303.333 rtt:95.077/48.14 ato:40 '
            'mss:1348 pmtu:1500 rcvmss:1348 advmss:1448 cwnd:7 '
            'ssthresh:4 bytes_sent:276685 bytes_retrans:524 '
            'bytes_acked:276162 bytes_received:810911 segs_out:1827 '
            'segs_in:1334 data_segs_out:806 data_segs_in:1223 send '
            '793967bps lastsnd:800 lastrcv:667 lastack:667 pacing_rate '
            '952752bps delivery_rate 1561688bps delivered:803 '
            'app_limited busy:41095ms retrans:0/9 dsack_dups:5 '
            'rcv_rtt:38.584 rcv_space:26731 rcv_ssthresh:122896 minrtt:26.457'
        )
        self.assertEqual(parse_ss_tip(example1),
                         ConnectionInfo(pid=1367, fd=7,
                                        bytes_sent=276685,
                                        bytes_received=810911))


class TestReadNetPerProcess(unittest.TestCase):
    def test_parse(self):
        for info in read_net_per_process():
            self.assertIsNotNone(info)
            self.assertIsInstance(info.pid, int)
            self.assertTrue(info.pid > 0)
            self.assertIsInstance(info.fd, int)
            self.assertTrue(info.fd > 0)
            self.assertIsInstance(info.bytes_sent, int)
            self.assertIsInstance(info.bytes_received, int)


if __name__ == '__main__':
    unittest.main()
