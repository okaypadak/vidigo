"""Uygulama kapatma sinyallerini sessiz ve tutarlı şekilde yönetir."""

import os
import signal
import sys


def _exit_on_sigint(_signum, _frame):
    """Ctrl+C ile çalışan işlemi log/traceback üretmeden hemen sonlandır."""
    sys.stderr.write("\nKullanıcı kapattı.\n")
    sys.stderr.flush()
    os._exit(0)


def install_sigint_exit_handler():
    """Ana iş parçacığında Ctrl+C için sessiz kapatma davranışını kur."""
    signal.signal(signal.SIGINT, _exit_on_sigint)
