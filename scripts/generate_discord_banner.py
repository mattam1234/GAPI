from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 680, 240
OUT_PATH = 'static/discord-bot-banner-680x240.png'


def load_font(size: int, bold: bool = False):
    candidates = [
        'C:/Windows/Fonts/seguisb.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',
        'C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


img = Image.new('RGB', (WIDTH, HEIGHT), '#0f172a')
draw = ImageDraw.Draw(img)

# Gradient background
for y in range(HEIGHT):
    t = y / (HEIGHT - 1)
    r = int(34 + (22 - 34) * t)
    g = int(45 + (33 - 45) * t)
    b = int(91 + (62 - 91) * t)
    draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

# Accent glow circles
draw.ellipse((470, -80, 760, 210), fill=(99, 102, 241))
draw.ellipse((520, 80, 820, 360), fill=(139, 92, 246))

# Dark overlay to soften right-side glow
draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(0, 0, 0, 70))

# Left card
card = (26, 24, 430, 214)
draw.rounded_rectangle(card, radius=22, fill=(15, 23, 42), outline=(99, 102, 241), width=2)

# Bot badge
draw.rounded_rectangle((48, 45, 124, 73), radius=14, fill=(99, 102, 241))
badge_font = load_font(18, bold=True)
draw.text((61, 50), 'BOT', font=badge_font, fill='white')

# Title + subtitle
title_font = load_font(39, bold=True)
sub_font = load_font(20)
draw.text((48, 84), 'GAPI Discord', font=title_font, fill='white')
draw.text((48, 130), 'Game nights made effortless', font=sub_font, fill=(191, 219, 254))

# Command chips
chip_font = load_font(16, bold=True)
chips = ['/pick', '/vote', '/common']
chip_x = 48
for label in chips:
    tw = draw.textlength(label, font=chip_font)
    chip_w = int(tw + 26)
    draw.rounded_rectangle((chip_x, 166, chip_x + chip_w, 197), radius=12, fill=(30, 41, 59))
    draw.text((chip_x + 13, 173), label, font=chip_font, fill=(224, 231, 255))
    chip_x += chip_w + 10

# Right-side icon block (simple gamepad shape)
draw.rounded_rectangle((470, 58, 638, 182), radius=28, fill=(30, 41, 59), outline=(129, 140, 248), width=2)
# D-pad
draw.rounded_rectangle((515, 100, 545, 112), radius=4, fill=(226, 232, 240))
draw.rounded_rectangle((524, 91, 536, 121), radius=4, fill=(226, 232, 240))
# Buttons
draw.ellipse((578, 95, 596, 113), fill=(244, 114, 182))
draw.ellipse((603, 110, 621, 128), fill=(56, 189, 248))
draw.ellipse((604, 84, 622, 102), fill=(250, 204, 21))
# Center dots
draw.ellipse((560, 121, 568, 129), fill=(148, 163, 184))
draw.ellipse((572, 121, 580, 129), fill=(148, 163, 184))

# Footer text
footer_font = load_font(14)
draw.text((474, 193), 'Multiplayer • Slash Commands', font=footer_font, fill=(203, 213, 225))

img.save(OUT_PATH, 'PNG', optimize=True)
print(f'Generated {OUT_PATH} ({WIDTH}x{HEIGHT})')
