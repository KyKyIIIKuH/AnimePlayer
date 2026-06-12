import sys
import os

def get_app_path():
	script_dir = os.environ.get('SCRIPT_DIR')
	if script_dir:
		return script_dir
	appimage = os.environ.get('APPIMAGE')
	if appimage:
		return os.path.dirname(appimage)
	owd = os.environ.get('OWD')
	if owd:
		return owd
	if getattr(sys, 'frozen', False):
		return os.path.dirname(sys.executable)
	elif __file__:
		return os.path.dirname(os.path.realpath(__file__))
	return os.getcwd()

pathname = get_app_path()
