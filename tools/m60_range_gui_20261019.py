"""Use the owned graphical client to inspect the server-delivered M60 metadata."""
from tools import groza_gui_20261019 as gui
gui.REPORT=gui.ROOT/'reports/m60-range-20261019'
gui.PRIVATE=gui.ROOT/'.secrets/m60-range-20261019.json'
if __name__=='__main__':gui.main()
