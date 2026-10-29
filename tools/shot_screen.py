# -*- coding: utf-8 -*-
"""截全屏，用于确认打包后的 exe 窗口显示正常。"""
import sys
import time

from PIL import ImageGrab

time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 4)
im = ImageGrab.grab(all_screens=True)
out = sys.argv[2] if len(sys.argv) > 2 else "screen.png"
im.save(out, "PNG")
print("saved", out, im.size)
