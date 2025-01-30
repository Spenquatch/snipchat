from PIL import Image, ImageDraw

# Create a new image with a transparent background
size = (32, 32)
icon = Image.new('RGBA', size, (0, 0, 0, 0))

# Create a drawing object
draw = ImageDraw.Draw(icon)

# Draw a simple chat bubble
draw.rectangle([4, 4, 28, 24], fill=(65, 105, 225), outline=(255, 255, 255), width=1)
draw.polygon([(12, 24), (18, 24), (15, 28)], fill=(65, 105, 225), outline=(255, 255, 255), width=1)

# Save the icon
icon.save('icon.png') 