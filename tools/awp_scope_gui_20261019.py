"""Use the isolated, pinned native client with owned AWP QA credentials."""
from tools import groza_gui_20261019 as gui
gui.REPORT=gui.ROOT/'reports/awp-scope-20261019'
gui.PRIVATE=gui.ROOT/'.secrets/awp-scope-20261019.json'
if __name__=='__main__':gui.main()
