"""Use the existing owned client copy for the separate icon QA fixture."""
from tools import groza_gui_20261019 as gui
gui.REPORT=gui.ROOT/'reports/groza-icon-20261019'
gui.PRIVATE=gui.ROOT/'.secrets/groza-icon-20261019.json'
if __name__=='__main__':gui.main()
