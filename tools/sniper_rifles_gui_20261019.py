"""Pinned isolated native client for SVD/HK checks on the hosting server."""
from tools import groza_gui_20261019 as gui
gui.REPORT=gui.ROOT/'reports/sniper-rifles-20261019'
gui.PRIVATE=gui.ROOT/'.secrets/sniper-rifles-20261019.json'
if __name__=='__main__':gui.main()
