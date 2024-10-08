#!/usr/bin/env python3

import os
import time
from base import Base
from settings import Settings
from matrixcontroller import MatrixController
from imagecontroller import (
    TextImageController,
    FileImageController,
    GifFileImageController,
    URLImageController,
    NetworkWeatherImageController,
    DiscAnimationsImageController,
)


class HawksSettings(Settings):
    def __init__(self):
        super().__init__(self)
        self.load_from_file()
        self.hawks = None
        self.internal.add("hawks")
        self.internal.add("filepath")
        self.internal.add("debug")
        self.set("filepath", "")
        self.set("debug", False)
        self.set("bgcolor", "blue", helptext="Background color when rendering text")
        self.set("outercolor", "black", helptext="Outer color of rendered text")
        self.set("innercolor", "green", helptext="Inner color of rendered text")
        self.set("bgbrightness", 0, helptext="background brightness of rainbow background")
        self.set("font", "FreeSansBold", helptext="Font to use when rendering text")
        self.set("x", 0)
        self.set("y", 0)
        self.set("rows", 32, helptext="Image height", choices=[32, 64, 128])
        self.set("cols", 32, helptext="Image width", choices=[32, 64, 128])
        self.set("p_rows", 32, helptext="Matrix height", choices=[32, 64, 128])
        self.set("p_cols", 32, helptext="Matrix width", choices=[32, 64, 128, 256])
        self.set(
            "decompose",
            False,
            helptext="Display is a chain of two 64x32 RGB LED matrices arranged to form a big square",
            choices=[False, True],
        )
        self.set("text", "12", helptext='Text to render (if filename is "none")')
        self.set("textsize", 27)
        self.set("thickness", 1, helptext="Thickness of outercolor border around text")
        self.set(
            "animation",
            "none",
            helptext='Options are "waving" or "none"',
            choices=["none", "waving", "disc_animations", "glitch"],
        )
        self.set("amplitude", 0.4, helptext="Amplitude of waving animation")
        self.set("fps", 16, helptext="FPS of waving animation")
        self.set("period", 2000, helptext="Period of waving animation")
        self.set("filename", "none", helptext='Image file to display (or "none")')
        self.set("autosize", True, choices=[True, False])
        self.set("margin", 2, helptext="Margin of background color around text")
        self.set("brightness", 255, helptext="Image brighness, full bright = 255")
        self.set("back_and_forth", False, helptext="Loop GIF back and forth", choices=[False, True])
        self.set("url", "", helptext="Fetch image from url")
        self.set("urls", "", choices=[])
        self.set("urls_file", "", helptext="File containing image urls, one url per line")
        self.set("config_file", ".hawks.json", helptext="Hawks config file for image urls and saved configs (JSON)")
        self.set(
            "disc",
            False,
            helptext="Display is a 255-element DotStar disc",
            choices=[False, True],
        )
        self.set(
            "transpose",
            "none",
            helptext="PIL transpose operations are supported",
            choices=[
                "none",
                "FLIP_LEFT_RIGHT",
                "FLIP_TOP_BOTTOM",
                "ROTATE_90",
                "ROTATE_180",
                "ROTATE_270",
                "TRANSPOSE",
            ],
        )
        self.set("rotate", 0, helptext="Rotation in degrees")
        self.set(
            "mock", False, helptext="Display is mock rgbmatrix", choices=[False, True]
        )
        self.set(
            "mode",
            "text",
            helptext="Valid modes are 'text', 'file', 'url', and 'network_weather'",
            choices=["text", "file", "url", "network_weather", "disc_animations"],
        )
        self.set("gif_frame_no", 0, helptext="Frame number of gif to statically display (when not animating)")
        self.set("gif_speed", 1.0, helptext="Multiplier for gif animation speed")
        self.set("gif_loop_delay", 0, helptext="Delay (ms) between repeatations of an animated gif")
        self.set("gif_override_duration_zero", False, helptext="Use 100ms frame time instead of 0", choices=[True, False])
        self.set("animate_gifs", True, choices=[True, False], helptext="Animate animated GIFs")
        self.set("zoom", False, choices=[True, False], helptext="Crop images to fill screen")
        self.set("zoom_center", True, choices=[True, False], helptext="When zooming, zoom into center of image")
        self.set("zoom_level", 1.0, helptext="Custom zoom level")
        self.set("fit", False, choices=[True, False], helptext="Fit image to display")
        self.set("filter", "none", choices=["none", "halloween"], helptext="Filter to apply to image")
        

    def set(self, name, value, show=True, **kwargs):
        """
        Write the value to ourself.
        If we are configured with a reference to a Hawks object, check the settings of its
        MatrixController. If the MatrixController has this setting, write it there, too.
        Some of our settings are intended for ImageControllers, but since ImageControllers are not
        persistent, we have nowhere to write to them at this time.  We interrogate the ImageController
        classes at create time to understand which settings to pass to their constructors.
        """

        super().set(name, value, **kwargs)
        if self.hawks:
            if name in self.hawks.ctrl.settings:
                setattr(self.hawks.ctrl, name, self.get(name))
            if show:
                self.hawks.show()

    def render(self, names):
        """
        Renders the named settings only. This is used to pass only the relevant settings to the
        constructors of Controllers.
        """

        return dict((name, self.get(name)) for name in names)


class Hawks(Base):
    """
    Implements the base logic of the sign. Passes the right parameters to the ImageController's constrctor,
    interprets the settings enough to understand which ImageController to use and which settings to
    pass it.
    """

    PRESETS = {
        "dark": {"bgcolor": "black", "innercolor": "blue", "outercolor": "green"},
        "bright": {"bgcolor": "blue", "innercolor": "black", "outercolor": "green"},
        "blue_on_green": {
            "bgcolor": "green",
            "innercolor": "blue",
            "outercolor": "black",
        },
        "green_on_blue": {
            "bgcolor": "blue",
            "innercolor": "green",
            "outercolor": "black",
        },
        "christmas": {
            "bgcolor": "green",
            "innercolor": "red",
            "outercolor": "black",
            "text": "12",
            "textsize": 27,
            "x": 0,
            "y": 2,
            "animation": "none",
            "thickness": 1,
        },
        "none": {},
    }

    ANIMATIONS = ["waving"]

    def __init__(self, *args, **kwargs):
        self.settings = HawksSettings()
        self.settings.save("defaults")

        self.debug_file = open(f"/tmp/{os.getpid()}", "w")

        preset = None

        for k, v in kwargs.items():
            if k in self.settings:
                self.settings.set(k, v)
            elif k == "preset":
                preset = v
            else:
                setattr(self, k, v)

        self.ctrl = MatrixController(**self.settings.render(MatrixController.settings))
        self.settings.hawks = self

        if preset:
            self.apply_preset(preset)

    def db(self, msg):
        self.debug_file.write(f"{msg}\n")

    def apply_preset(self, preset):
        if preset in Hawks.PRESETS:
            for k, v in Hawks.PRESETS[preset].items():
                self.settings.set(k, v, show=False)
            self.show()
            return True
        return False

    def show(self):
        self.db(time.time())
        self.stop()
        img_ctrl = None
        if self.settings.mode == "url":
            if self.settings.url == "":
                self.settings.url = self.settings.urls
            img_ctrl = URLImageController(
                **self.settings.render(URLImageController.settings)
            )
        elif self.settings.mode == "file" and self.settings.filename != "none":
            img_ctrl = FileImageController(
                **self.settings.render(FileImageController.settings)
            )
        elif self.settings.mode == "network_weather":
            img_ctrl = NetworkWeatherImageController(
                **self.settings.render(NetworkWeatherImageController.settings)
            )
        elif self.settings.mode == "disc_animations":
            #self.ctrl.disc_animations()
            img_ctrl = DiscAnimationsImageController(
                **self.settings.render(DiscAnimationsImageController.settings)
            )
        else:
            img_ctrl = TextImageController(
                **self.settings.render(TextImageController.settings)
            )

        if img_ctrl:
            frames = img_ctrl.render()
            if not frames:
                print("Image controller returned empty frames, not setting frames")
                return self.ctrl.show()

            if "filter" in self.settings and self.settings.filter and self.settings.filter != "none":
                frames = getattr(img_ctrl, "filter_" + self.settings.filter)(frames)

            if self.settings.animation == "glitch":
                self.ctrl.render_state["callback"] = getattr(self.ctrl, "render_glitch", None)
                flash_image_ctrl_settings = self.settings.render(FileImageController.settings)
                flash_image_ctrl_settings["filename"] = "img/jack3.jpg"
                flash_image_ctrl = FileImageController(**flash_image_ctrl_settings)
                self.ctrl.render_state["flash_image"] = self.ctrl.transform_and_reshape(flash_image_ctrl.render())[0][0][0]
                print(self.ctrl.render_state["flash_image"])

            self.ctrl.set_frames(frames)

        return self.ctrl.show()

    def screenshot(self):
        return self.ctrl.screenshot()

    def stop(self):
        return self.ctrl.stop()

    def start(self):
        return self.ctrl.start()
