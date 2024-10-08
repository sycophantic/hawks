#!/usr/bin/env python3

import json
import math
import requests
import sys
import tempfile
import time
from matrixcontroller import MatrixController
from PIL import Image, ImageDraw, ImageFont, ImageColor, GifImagePlugin, UnidentifiedImageError
from random import randint, choice
from urllib.parse import unquote


class ImageController(object):
    """
    Image Controller renders a list of tuples of RGB PIL.Image objects and
    durations in ms. Configure it with a reference to a Matrix Controller that
    provides the properties() method, so that the Image Controller can learn
    the properties of the display (width, height). Matrix Controller should also
    offer a brightness_mask() method, allowing the Image Controller to pass in a
    list of integers representing an image bitmask. Where the brightness mask is
    non-negative, the matrix must leave pixels at the specified brightness.
    """

    settings = [
        "cols",
        "rows",
        "animation",
        "period",
        "fps",
        "amplitude",
        "filter",
        "mock",
    ]

    def __init__(self, *args, **kwargs):
        """
        ImageController objects should not pre-render images in __init__, as
        some properties of the ImageController will be assigned by the
        MatrixController. MatrixController will only call ImageController.render()
        at MatrixController.show() time, which is infrequent. It is OK to to
        expensive calculations in render().
        """
        self.brightness_mask = None
        self.cols = 32
        self.rows = 32
        self.period = 1000
        self.fps = 16
        self.amplitude = 1
        self.animation = None
        self.filter = None
        for (k, v) in kwargs.items():
            setattr(self, k, v)
        super().__init__()

    def render(self):
        return [()]

    @property
    def image(self):
        try:
            frames = self.render()
            if len(frames) == 1:
                return self.render()[0][0]
            else:
                Image.save("/tmp/tmp.gif", save_all=True, append_images=[frame[0] for frame in frames], duration=[frame[1] for frame in frames], loop=0)
                return open("/tmp/tmp.gif", "rb").read()
        except TypeError or IndexError:
            return None

    def shift_column(self, image, column, delta):
        rows = self.rows
        if delta == 0:
            return image
        if delta > 0:
            # positive == up
            # from 0 to rows-delta, pull from row+delta.
            # from rows-delta to rows-1, black
            for n in range(0, rows - delta):
                image.putpixel((column, n), image.getpixel((column, n + delta)))
            for n in range(rows - delta, rows):
                image.putpixel((column, n), (0, 0, 0))
        else:
            # negative == down
            # make delta positive
            # from rows-1 to delta, pull from row-delta
            # from delta to 0, black
            delta = 0 - delta
            for n in range(rows - 1, delta, -1):
                image.putpixel((column, n), image.getpixel((column, n - delta)))
            for n in range(0, delta):
                image.putpixel((column, n), (0, 0, 0))

    def frames_equal(self, one, two):
        if not one or not two:
            return False
        for o, t in zip(one.getdata(), two.getdata()):
            if o != t:
                return False
        return True

    def multiply_pixel(self, pixel, value):
        return tuple([int(c * value) for c in pixel])

    def average_anim_frames(self, group):
        """
        group is a list of indices of self.frames
        The frames should represent repetitions of the first image
        and one instnace of the next image, a set of duplicate
        frames and one instance of what the next frame will be.  This
        method should leave the first and last frames untouched and
        replace each of the intermediate frames with a combination of the two.
        """

        if not group:
            return
        num_frames = len(group)
        if num_frames <= 2:
            return
        num_frames -= 1

        saf = self.frames
        # we can redo this to only fetch the first and last.  we compute the ones in the middle.
        group_data = [saf[n].getdata() for n in group]
        new_data = [[] for n in group]
        num_pixels = len(list(group_data[0]))

        for pixel_no in range(0, num_pixels):
            first = group_data[0][pixel_no]
            last = group_data[-1][pixel_no]
            for idx, frame_no in enumerate(group):
                left = self.multiply_pixel(
                    group_data[0][pixel_no], float(num_frames - idx) / num_frames
                )
                right = self.multiply_pixel(
                    group_data[-1][pixel_no], float(idx) / num_frames
                )
                new_data[idx].append(tuple([l + r for l, r in zip(left, right)]))
        for idx, frame_no in enumerate(group):
            if idx == 0 or idx == num_frames:
                continue
            saf[frame_no].putdata(new_data[idx])

    def rainbow_color_from_value(self, value):
        border = 0
        num_buckets = 6
        max_value = 1024 # implicit min value of 0
        bucket = (max_value - border * 2) / num_buckets
        value = min(value, bucket * num_buckets) # bucket * num_buckets is the actual max value
        r = 0
        g = 0
        b = 0
        bright = 255

        if value < border:
            # red
            r = bright
            g = 0
            b = 0
        elif value < border + bucket * 1:
            # red + increasing green
            value -= border + bucket * 0
            value = (value * bright) / bucket
            r = bright
            g = value
            b = 0
        elif value < border + bucket * 2:
            # green + decreasing red
            value -= border + bucket * 1
            value = bucket - value
            value = (value * bright) / bucket
            r = value
            g = bright
            b = 0
        elif value < border + bucket * 3:
            # green + increasing blue
            value -= border + bucket * 2
            value = (value * bright) / bucket
            r = 0
            g = bright
            b = value
        elif value < border + bucket * 4:
            # blue + decreasing green
            value -= border + bucket * 3
            value = bucket - value
            value = (value * bright) / bucket
            r = 0
            g = value
            b = bright
        elif value < border + bucket * 5:
            # blue + increasing red
            value -= border + bucket * 4
            value = (value * bright) / bucket
            r = value
            g = 0
            b = bright
        else:
            # red + decreasing blue
            value -= border + bucket * 5
            value = bucket - value
            value = (value * bright) / bucket
            r = bright
            g = 0
            b = value
        return (int(g), int(r), int(b))


    def init_anim_frames(self, image, count=None):
        if count is None:
            count = self.fps
        return [image.copy() for n in range(0, count)]

    def glitch_effect_flicker(self, image, color="black"):
        blank = Image.new("RGB", (self.cols, self.rows), color)
        return [(blank, randint(10, 50))]

    def glitch_effect_shift(self, image, color="black"):
        blank = Image.new("RGB", (self.cols, self.rows), color)
        blank.paste(image, (randint(1, self.cols), randint(1, self.rows)))
        return [(blank, randint(10, 50))]

    def generate_glitch_frames(self, image, glitchiness=5):
        """
        glitchiness is the chance out of 100 that any given frame is going to be a glitch.
        """
        glitch_functions = [
            self.glitch_effect_flicker,
            self.glitch_effect_shift,
        ]
        count = randint(self.fps, 4*self.fps)
        frames = []
        for frame in range(count):
            if randint(1, 100) <= glitchiness:
                frames.extend(choice(glitch_functions)(image))
            else:
                frames.append((image, 500))
        return frames

    def generate_waving_frames(self, image):
        cols = self.cols
        frames = self.init_anim_frames(image)
        ms_per_frame = self.period / self.fps
        wavelength_radians = math.pi * 2.0
        phase_step_per_frame = wavelength_radians / self.fps
        radians_per_pixel = wavelength_radians / cols
        phase = 0.0
        amplitude = self.amplitude
        # first pass
        for n in range(0, self.fps):
            for c in range(0, cols):
                radians = radians_per_pixel * c + phase
                delta_y = int(
                    round((math.sin(radians) * amplitude) / radians_per_pixel)
                )  # assumes rows == cols!
                self.shift_column(frames[n], c, delta_y)
            phase -= phase_step_per_frame
        # second pass
        group = []
        for n in range(0, self.fps):
            group.append(n)
            if not self.frames_equal(frames[group[0]], frames[n]):
                self.average_anim_frames(group)
                group = [n]
        frame_times = [ms_per_frame for frame in frames]
        return list(zip(frames, frame_times))

    def generate_rainbow_frames(self, image):
        frames = self.init_anim_frames(image)
        color_delta = 1024.0 / (self.cols * self.rows)
        bg_rgb = ImageColor.getrgb(self.bgcolor)
        color_value = 0.0
        for idx, frame in enumerate(frames):
            color_value = 1024.0 * idx / len(frames)
            pixels = frame.getdata()
            new_pixels = []
            for pixel in pixels:
                if pixel == bg_rgb:
                    new_pixel = self.rainbow_color_from_value(int(color_value))
                    if self.bgbrightness:
                        new_pixel = tuple([int(float(p)*float(self.bgbrightness)/255) for p in new_pixel])   
                    new_pixels.append(new_pixel)
                else:
                    new_pixels.append(pixel)
                color_value += color_delta
                if color_value > 1024:
                    color_value -= 1024
            frame.putdata(new_pixels)
        return list(zip(frames, [50 for frame in frames]))

    def filter_halloween(self, frames):
        spooky = (255, 127, 00)
        for frame in frames:
            new_frame = []
            for pixel in list(frame[0].getdata()):
                pixel_brightness = (pixel[0] + pixel[1] + pixel[2]) / (255 * 3)
                new_frame.append(tuple([int(c * pixel_brightness) for c in spooky]))
            frame[0].putdata(new_frame)
        return frames

    def filter_christmas(self, frames):
        for frame in frames:
            new_frame = []
            for pixel in list(frame[0].getdata()):
                new_pixel = [max(255, pixel[0] * 2), pixel[1] * 2, int(pixel[2] / 4)]
                if new_pixel[0] > new_pixel[1]:
                    new_pixel[1] = int(new_pixel[1] / 4)
                else:
                    new_pixel[0] = int(new_pixel[0] / 4)
                new_frame.append(tuple(new_pixel))
            frame[0].putdata(new_frame)
        return frames


class TextImageController(ImageController):
    settings = ImageController.settings + [
        "bgcolor",
        "outercolor",
        "innercolor",
        "bgrainbow",
        "bgbrightness",
        "font",
        "text",
        "textsize",
        "thickness",
        "autosize",
        "margin",
        "x",
        "y",
    ]

    def __init__(self, *args, **kwargs):
        self.bgcolor = "blue"
        self.outercolor = "black"
        self.innercolor = "white"
        self.bgrainbow = False
        self.bgbrightness = 0
        self.font = "FreeSansBold"
        self.text = "12"
        self.textsize = 27
        self.thickness = 1
        self.autosize = True
        self.margin = 2
        self.x = 0
        self.y = 0
        super().__init__(*args, **kwargs)

    def render(self, autosize=True, ignore_animation=False):
        image = Image.new("RGB", (self.cols, self.rows), self.bgcolor)
        draw = ImageDraw.Draw(image)
        text = unquote(self.text.upper())
        font = ImageFont.truetype(self.font, self.textsize)

        if autosize and self.autosize:
            self._autosize()

        font = ImageFont.truetype(self.font, self.textsize)

        x = self.x
        y = self.y

        for dx in range(0 - self.thickness, self.thickness + 1):
            for dy in range(0 - self.thickness, self.thickness + 1):
                draw.text((x - dx, y - dy), text, fill=self.outercolor, font=font)
                draw.text((x + dx, y - dy), text, fill=self.outercolor, font=font)
                draw.text((x - dx, y + dy), text, fill=self.outercolor, font=font)
                draw.text((x + dx, y + dy), text, fill=self.outercolor, font=font)

        draw.text((x, y), text, fill=self.innercolor, font=font)

        if not ignore_animation:
            if self.animation == "waving":
                return self.generate_waving_frames(image)
            elif self.animation == "glitch":
                return self.generate_glitch_frames(image)
            elif self.animation == "rainbow":
                return self.generate_rainbow_frames(image)

        return [(image, 0)]

    def col_only_bgcolor(self, image_data, col):
        if col < 0 or col >= self.cols:
            raise Exception(
                "Column {0} is out of bounds (0, {1})".format(col, self.cols)
            )

        bgcolor = ImageColor.getrgb(self.bgcolor)
        px_no = col
        while px_no < len(image_data):
            if image_data[px_no] != bgcolor:
                return False
            px_no += self.cols
        return True

    def row_only_bgcolor(self, image_data, row):
        if row < 0 or row >= self.rows:
            raise Exception(
                "Column {0} is out of bounds (0, {1})".format(row, self.rows)
            )

        bgcolor = ImageColor.getrgb(self.bgcolor)
        px_no = row * self.cols
        while px_no < (row + 1) * self.cols and px_no < len(image_data):
            if image_data[px_no] != bgcolor:
                return False
            px_no += 1
        return True

    def measure_left_margin(self, image_data):
        col = 0
        while col < self.cols and self.col_only_bgcolor(image_data, col):
            col += 1
        return col

    def measure_right_margin(self, image_data):
        col = self.cols - 1
        while col >= 0 and self.col_only_bgcolor(image_data, col):
            col -= 1
        return (self.cols - 1) - col

    def measure_top_margin(self, image_data):
        row = 0
        while row < self.rows and self.row_only_bgcolor(image_data, row):
            row += 1
        return row

    def measure_bottom_margin(self, image_data):
        row = self.rows - 1
        while row >= 0 and self.row_only_bgcolor(image_data, row):
            row -= 1
        return (self.rows - 1) - row

    def align_and_measure(self):
        image_data = self.render(autosize=False, ignore_animation=True)[0][0].getdata()

        left_margin = self.measure_left_margin(image_data)
        self.x = 0

        top_margin = self.measure_top_margin(image_data)
        self.y = 0

        if self.margin != left_margin or self.margin != top_margin:
            image = self.render(autosize=False, ignore_animation=True)
            image_data = image[0][0].getdata()

        left_margin = self.measure_left_margin(image_data)
        top_margin = self.measure_top_margin(image_data)
        right_margin = self.measure_right_margin(image_data)
        bottom_margin = self.measure_bottom_margin(image_data)

        return (left_margin, right_margin, top_margin, bottom_margin)

    def _autosize(self):
        self.x = 0
        self.y = 0
        self.textsize = 10

        left_margin, right_margin, top_margin, bottom_margin = self.align_and_measure()

        # make the text big enough
        count = 0
        while right_margin > self.margin and bottom_margin > self.margin:
            self.textsize += 1
            (
                left_margin,
                right_margin,
                top_margin,
                bottom_margin,
            ) = self.align_and_measure()
            count += 1

        # make sure it is not too big
        while (
            right_margin < self.margin or bottom_margin < self.margin
        ) and self.textsize > 0:
            self.textsize -= 1
            (
                left_margin,
                right_margin,
                top_margin,
                bottom_margin,
            ) = self.align_and_measure()

        # center the text in both dimensions
        self.x += int((right_margin - left_margin) / 2)
        self.y += int((bottom_margin - top_margin) / 2)


class FileImageController(ImageController):
    settings = [
      "filename",
      "animate_gifs",
      "gif_frame_no",
      "gif_speed",
      "gif_loop_delay",
      "gif_override_duration_zero",
    ]
    settings.extend(ImageController.settings)

    def __init__(self, filename, **kwargs):
        self.filename = filename
        self.animate_gifs = True
        self.gif_frame_no = 0
        self.gif_speed = 1
        self.gif_loop_delay = 0
        self.override_duration_zero = False
        super().__init__(**kwargs)

    def render(self):
        try:
            image = Image.open(unquote(self.filename))
        except UnidentifiedImageError as e:
            print(f"Unable to open image file {self.filename}: {e}")
            return []

        if hasattr(image, "is_animated") and image.is_animated:
            return GifFileImageController(
                self.filename,
                animate_gifs=self.animate_gifs,
                gif_frame_no=self.gif_frame_no,
                gif_speed=self.gif_speed,
                gif_loop_delay=self.gif_loop_delay,
                gif_override_duration_zero=self.gif_override_duration_zero,
            ).render()

        image = image.convert("RGB")
        return [(image, 0)]


class GifFileImageController(FileImageController):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_frames()

    def init_frames(self):
        self.frames = []
        with Image.open(unquote(self.filename)) as gif:
            for n in range(0, gif.n_frames):
                gif.seek(n)
                image = gif.convert("RGB")
                if self.animate_gifs:
                    duration = int(gif.info["duration"])
                    if duration == 0 and self.gif_override_duration_zero:
                        duration = 100
                    if n == gif.n_frames - 1:
                        duration += self.gif_loop_delay * self.gif_speed  # hack
                else:
                    if n == self.gif_frame_no:
                        duration = 0
                    else:
                        duration = 1
                duration = int(duration * (1 / self.gif_speed))
                self.frames.append((image, duration))
                if not duration:
                    # -0 duration frame will be shown forever, no value in rendering any more
                    return

    def render(self):
        return self.frames



class URLImageController(FileImageController):
    settings = [ "url" ]
    settings.extend(FileImageController.settings)

    def __init__(self, url, **kwargs):
        self.url = url
        super().__init__(**kwargs)
        self.filename = tempfile.mktemp()
        self.fetch_image()

    def fetch_image(self):
        response = requests.get(self.url)
        if response.status_code != 200:
            raise Exception("Error fetching {}: status code {}".format(self.url, response.status_code))
        with open(self.filename, "wb") as TMPFILE:
            TMPFILE.write(response.content)

    def render(self):
        return FileImageController(
            self.filename,
            animate_gifs = self.animate_gifs,
            gif_frame_no = self.gif_frame_no,
            gif_speed = self.gif_speed,
            gif_loop_delay = self.gif_loop_delay,
            gif_override_duration_zero = self.gif_override_duration_zero,
        ).render()
        os.unlink(self.filename)


class NetworkWeatherImageController(ImageController):
    """
    WIP
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.network_weather_data = None
        self.network_weather_image = Image.new("RGB", (self.cols, self.rows), "black")

        #
        # on a 32x32 6mm pitch LED matrix
        # if you happen to have a 5 7/8" wide Google Cloud Platform plexiglass logo
        # if you center it horizontally and align its top with the top of the panel
        # these are the lights that it will cover.
        #
        # no one else will use this EVER
        #
        # fmt: off
        self.gcp_logo_pixels = [
                                                      14, 15, 16, 17,

                                          43, 44, 45, 46, 47, 48, 49, 50, 51, 52,

                                     74,  75,  76,  77,  78,  79,  80,  81,  82,  83,  84,  85,

                               105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118,

                          136, 137, 138, 139, 140, 141,                          147, 148, 149, 150, 151,

                          168, 169, 170, 171,                                              181, 182, 183, 184,

                     199, 200, 201, 202, 203, 204,                                         213, 214, 215, 216,

                230, 231, 232, 233, 234, 235, 236, 237, 238,                               245, 246, 247, 248,

                262, 263, 264, 265, 266, 267, 268, 269, 270, 271,                               278, 279, 280, 281,

           293, 294, 295, 296, 297, 298, 299, 300, 301, 302,                                    310, 311, 312, 313, 314,

      324, 325, 326, 327, 328,                     332, 333,                                         343, 344, 345, 346, 347,

      356, 357, 358, 359,                                                                                 376, 377, 378, 379,

      388, 389, 390, 391,                                                                                 408, 409, 410, 411,

      420, 421, 422, 423,                                                                                 440, 441, 442, 443,

      452, 453, 454, 455,                                                                                 472, 473, 474, 475,

      484, 485, 486, 487, 488,                                                                       503, 504, 505, 506, 507,

           517, 518, 519, 520, 521, 522, 523, 524, 525, 526, 527, 528, 529, 530, 531, 532, 533, 534, 535, 536, 537, 538,

                550, 551, 552, 553, 554, 555, 556, 557, 558, 559, 560, 561, 562, 563, 564, 565, 566, 567, 568, 569,

                     583, 584, 585, 586, 587, 588, 589, 590, 591, 592, 593, 594, 595, 596, 597, 598, 599, 600,

                               617, 618, 619, 620, 621, 622, 623, 624, 625, 626, 627, 628, 629, 630

        ]
        # fmt: on

        self.gcp_logo_pixels.sort()

        # ImageControllers shouldn't render things in __init__, but the gcp
        # logo pixels only work for 32x32, so nothing the MatrixController
        # sets later is going to change this.

        n = 0
        p = 0
        self.brightness_mask = []
        self.not_gcp_logo_pixels = []
        while n < 32 * 32:
            if self.gcp_logo_pixels[p] == n:
                p += 1
                self.brightness_mask.append(255)
            else:
                self.brightness_mask.append(-1)
                self.not_gcp_logo_pixels.append(n)
            n += 1

        super().__init__(*args, **kwargs)

    def render(self):
        self.network_color = "black"
        img = Image.new("RGB", (self.cols, self.rows), self.network_color)
        img_data = list(img.getdata())
        for p in self.not_gcp_logo_pixels:
            img_data[p] = (255, 0, 0)
        for p in self.gcp_logo_pixels:
            img_data[p] = (255, 255, 255)

        self.network_weather_image.putdata(img_data)
        return [(self.network_weather_image, 0)]

    def network_weather_update(self):
        """
        Fetch the data needed to render the network weather.
        If the data has changed, call network_weather_anim_setup()
        """
        try:
            response = requests.get("https://status.cloud.google.com/incidents.json")
            if response.status_code == 200:
                new_network_weather_data = json.loads(response.text)
                if new_network_weather_data != self.network_weather_data:
                    self.network_weather_data = new_network_weather_data
        except ConnectionError as e:
            # Couldn't connect, try again next time
            pass

class DiscAnimationsImageController(ImageController):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def render(self):
        import disc

        circle_colors = []
        color = 100
        for circle in disc.Disc.circles:
            circle_colors.append(color)
            color += 100

        frames = []
        while True:
            if frames and circle_colors[0] == frames[0][0]:
                break
            frames.append([])
            for idx, circle in enumerate(disc.Disc.circles):
                color = self.rainbow_color_from_value(circle_colors[idx])
                for n in range(0, circle[1]):
                    frames[-1].append(color)
                circle_colors[idx] += 7
                if circle_colors[idx] >= 1024:
                    circle_colors[idx] = 0
        return frames



def main():
    ctrl = MatrixController(mock=True)
    ctrl.debug = True
    if len(sys.argv) > 1:
        if sys.argv[1].endswith(".gif"):
            ctrl.set_frames(GifFileImageController(sys.argv[1]).render())
        else:
            ctrl.set_frames(FileImageController(sys.argv[1]).render())
    else:
        ctrl.set_frames(TextImageController(animation="glitch").render())
    ctrl.show()
    while True:
        time.sleep(1000)


if __name__ == "__main__":
    main()
